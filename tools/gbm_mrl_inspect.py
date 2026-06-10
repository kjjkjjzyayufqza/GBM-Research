#!/usr/bin/env python3
"""Parse GBM MRL material files into per-material texture bindings.

An MRL binds textures per material through explicit material records; the
binding is keyed by the material name hash, not by table order:

```text
0x00  char[4]  magic "MRL\0"
0x04  u32      version (0x32)
0x08  u32      material count
0x0c  u32      texture count
0x18  u64      texture table offset (0x90-byte records, path at +0x10)
0x20  u64      material table offset (0x30-byte records)

material record:
  +0x08  u32   material name hash: ~crc32(name) of the MOD material name
  +0x20  u32   parameter block offset (file-absolute)

parameter block: 24-byte properties [tag u32, fill, value u32, 0, hash u32, 0]
terminated by tag 0. Properties whose tag low byte is 0xC2 reference the
texture table with 1-based indices; value 0 means the sampler is unbound.
```

A model often has several materials (HEAD, ARM, BACK, BODY, LEG) and may
reference textures owned by other models. The texture table order does NOT
follow the MOD material order (chr100009 stores HEAD, ARM, LEG, BACK, BODY),
so bindings must be resolved through the material records.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

MAGIC = b"MRL\x00"
MATERIAL_COUNT_OFFSET = 0x08
TEXTURE_COUNT_OFFSET = 0x0C
TEXTURE_TABLE_OFFSET_FIELD = 0x18
MATERIAL_TABLE_OFFSET_FIELD = 0x20
TEXTURE_RECORD_SIZE = 0x90
TEXTURE_RECORD_PATH_OFFSET = 0x10
MATERIAL_RECORD_SIZE = 0x30
MATERIAL_RECORD_NAME_HASH_OFFSET = 0x08
MATERIAL_RECORD_PARAM_OFFSET = 0x20
PROPERTY_SIZE = 24
TEXTURE_PROPERTY_TAG_LOW_BYTE = 0xC2
PAINT_BASE_PATTERN = re.compile(r"_P\d+_BM$")


@dataclass(frozen=True)
class MaterialTextures:
    index: int
    name: str
    base: str | None
    normal: str | None


def material_name_hash(name: str) -> int:
    """MT Framework resource name hash: bit-inverted CRC32 of the name."""
    return (~zlib.crc32(name.encode("ascii"))) & 0xFFFFFFFF


def read_texture_stems(data: bytes) -> list[str]:
    if data[:4] != MAGIC:
        raise ValueError("not an MRL file (missing MRL magic)")
    texture_count = struct.unpack_from("<I", data, TEXTURE_COUNT_OFFSET)[0]
    table_offset = struct.unpack_from("<Q", data, TEXTURE_TABLE_OFFSET_FIELD)[0]
    stems: list[str] = []
    for index in range(texture_count):
        start = table_offset + index * TEXTURE_RECORD_SIZE + TEXTURE_RECORD_PATH_OFFSET
        path = data[start : start + 0x80].split(b"\x00", 1)[0].decode("ascii")
        stems.append(path.replace("\\", "/").rsplit("/", 1)[-1])
    return stems


def read_material_records(data: bytes) -> list[tuple[int, list[int]]]:
    """Return (name_hash, 1-based texture indices) per material record."""
    if data[:4] != MAGIC:
        raise ValueError("not an MRL file (missing MRL magic)")
    material_count = struct.unpack_from("<I", data, MATERIAL_COUNT_OFFSET)[0]
    texture_count = struct.unpack_from("<I", data, TEXTURE_COUNT_OFFSET)[0]
    table_offset = struct.unpack_from("<Q", data, MATERIAL_TABLE_OFFSET_FIELD)[0]

    records: list[tuple[int, list[int]]] = []
    for index in range(material_count):
        record = table_offset + index * MATERIAL_RECORD_SIZE
        name_hash = struct.unpack_from(
            "<I", data, record + MATERIAL_RECORD_NAME_HASH_OFFSET
        )[0]
        param_offset = struct.unpack_from(
            "<I", data, record + MATERIAL_RECORD_PARAM_OFFSET
        )[0]
        if param_offset == 0 or param_offset >= len(data):
            raise ValueError(
                f"material record {index} has invalid parameter block offset "
                f"0x{param_offset:x}"
            )
        texture_indices: list[int] = []
        cell = param_offset
        while cell + PROPERTY_SIZE <= len(data):
            tag, _, value, _, _, _ = struct.unpack_from("<6I", data, cell)
            if tag == 0:
                break
            if tag & 0xFF == TEXTURE_PROPERTY_TAG_LOW_BYTE and value != 0:
                if value > texture_count:
                    raise ValueError(
                        f"material record {index} references texture {value} "
                        f"but the table has {texture_count} entries"
                    )
                texture_indices.append(value)
            cell += PROPERTY_SIZE
        records.append((name_hash, texture_indices))
    return records


def pick_base(stems: list[str]) -> str | None:
    bases = [stem for stem in stems if not stem.endswith("_NM")]
    if not bases:
        return None
    plain = [stem for stem in bases if not PAINT_BASE_PATTERN.search(stem)]
    return (plain or bases)[0]


def pick_normal(stems: list[str]) -> str | None:
    normals = [stem for stem in stems if stem.endswith("_NM")]
    return normals[0] if normals else None


def material_bindings(
    mrl_path: Path, material_names: list[str]
) -> list[MaterialTextures]:
    """Resolve texture bindings ordered by MOD material index.

    ``material_names`` is the MOD material name table; each name is matched
    to its MRL material record by name hash.
    """
    data = mrl_path.read_bytes()
    stems = read_texture_stems(data)
    records = read_material_records(data)
    by_hash: dict[int, list[int]] = {}
    for name_hash, texture_indices in records:
        if name_hash in by_hash:
            raise ValueError(
                f"{mrl_path}: duplicate material name hash 0x{name_hash:08x}"
            )
        by_hash[name_hash] = texture_indices

    bindings: list[MaterialTextures] = []
    for index, name in enumerate(material_names):
        name_hash = material_name_hash(name)
        if name_hash not in by_hash:
            raise ValueError(
                f"{mrl_path}: no material record for {name!r} "
                f"(hash 0x{name_hash:08x})"
            )
        referenced = [stems[value - 1] for value in by_hash[name_hash]]
        bindings.append(
            MaterialTextures(
                index=index,
                name=name,
                base=pick_base(referenced),
                normal=pick_normal(referenced),
            )
        )
    return bindings


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect GBM MRL texture bindings.")
    parser.add_argument("mrl", type=Path, help="Input .mrl file")
    parser.add_argument(
        "--mod",
        type=Path,
        help="Matching .mod file; resolves material names for the records.",
    )
    args = parser.parse_args()
    data = args.mrl.read_bytes()
    stems = read_texture_stems(data)
    report: dict[str, object] = {"mrl": str(args.mrl), "textures": stems}
    if args.mod:
        from gbm_mod_inspect import parse_header, read_material_names

        mod_data = args.mod.read_bytes()
        names = read_material_names(mod_data, parse_header(args.mod, mod_data))
        report["materials"] = [
            asdict(binding) for binding in material_bindings(args.mrl, names)
        ]
    else:
        report["material_records"] = [
            {
                "name_hash": f"0x{name_hash:08x}",
                "textures": [stems[value - 1] for value in texture_indices],
            }
            for name_hash, texture_indices in read_material_records(data)
        ]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
