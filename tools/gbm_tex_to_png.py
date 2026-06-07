#!/usr/bin/env python3
"""Convert Gundam Breaker Mobile TEX textures to PNG.

The format IDs are the byte at header offset 0x06. They match
``nDraw::Texture::mFormatTable`` in the Android arm64 ``libGUNS.so``:

* 0x01: raw RGBA8888.
* 0x07: raw RGBA4444.
* 0x14: ETC2 RGB8.
* 0x15: ETC2 RGBA8/EAC.

Only the largest mip is written to PNG. The remaining payload is the complete
mip chain and is retained in the source TEX file.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

try:
    import texture2ddecoder
except ImportError:  # pragma: no cover - optional dependency guard
    texture2ddecoder = None


DATA_OFFSET = 0x30

FORMAT_NAMES = {
    0x01: "RGBA8888",
    0x07: "RGBA4444",
    0x14: "ETC2_RGB8",
    0x15: "ETC2_RGBA8_EAC",
}


@dataclass(frozen=True)
class TexHeader:
    path: str
    version: int
    format_field: int
    format_id: int
    format_flags: int
    attr: int
    unk0a: int
    width: int
    height: int
    hword: int
    data_offset: int
    payload_size: int
    first_mip_size: int
    format_name: str


def parse_header(path: Path) -> TexHeader:
    data = path.read_bytes()
    if len(data) < DATA_OFFSET:
        raise ValueError(f"{path} is too small for a GBM TEX header")
    if data[:4] != b"TEX ":
        raise ValueError(f"{path} does not start with TEX magic")

    version, format_field, attr, unk0a = struct.unpack_from("<HHHH", data, 4)
    format_id = format_field & 0xFF
    format_flags = format_field >> 8
    width = struct.unpack_from("<H", data, 0x0C)[0]
    hword = struct.unpack_from("<H", data, 0x0E)[0]
    height = (hword & 0x03FF) << 3
    if width <= 0 or height <= 0:
        raise ValueError(f"{path} has invalid dimensions {width}x{height}")

    format_name = FORMAT_NAMES.get(format_id, f"UNKNOWN_0x{format_id:02x}")
    payload_size = len(data) - DATA_OFFSET
    first_mip_size = get_first_mip_size(format_id, width, height)

    return TexHeader(
        path=str(path),
        version=version,
        format_field=format_field,
        format_id=format_id,
        format_flags=format_flags,
        attr=attr,
        unk0a=unk0a,
        width=width,
        height=height,
        hword=hword,
        data_offset=DATA_OFFSET,
        payload_size=payload_size,
        first_mip_size=first_mip_size,
        format_name=format_name,
    )


def get_first_mip_size(format_id: int, width: int, height: int) -> int:
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    if format_id == 0x01:
        return width * height * 4
    if format_id == 0x07:
        return width * height * 2
    if format_id == 0x14:
        return block_w * block_h * 8
    if format_id == 0x15:
        return block_w * block_h * 16
    raise ValueError(f"unsupported TEX format ID 0x{format_id:02x}")


def rgba4444_to_rgba(payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 2
    if len(payload) < expected:
        raise ValueError(f"RGBA4444 payload too short: {len(payload)} < {expected}")

    output = bytearray(width * height * 4)
    for index in range(width * height):
        value = payload[index * 2] | (payload[index * 2 + 1] << 8)
        red = ((value >> 12) & 0x000F) * 17
        green = ((value >> 8) & 0x000F) * 17
        blue = ((value >> 4) & 0x000F) * 17
        alpha = (value & 0x000F) * 17
        output[index * 4 : index * 4 + 4] = bytes((red, green, blue, alpha))
    return bytes(output)


def decode_tex(path: Path) -> tuple[TexHeader, bytes]:
    header = parse_header(path)
    data = path.read_bytes()
    payload = data[header.data_offset : header.data_offset + header.first_mip_size]
    if len(payload) < header.first_mip_size:
        raise ValueError(
            f"{path} payload is too short for first mip: "
            f"{len(payload)} < {header.first_mip_size}"
        )

    if header.format_id == 0x01:
        rgba = payload
    elif header.format_id == 0x07:
        rgba = rgba4444_to_rgba(payload, header.width, header.height)
    elif header.format_id == 0x14:
        require_texture2ddecoder(header.format_name)
        rgba = texture2ddecoder.decode_etc2(payload, header.width, header.height)
        rgba = bgra_to_rgba(rgba)
    elif header.format_id == 0x15:
        require_texture2ddecoder(header.format_name)
        rgba = texture2ddecoder.decode_etc2a8(payload, header.width, header.height)
        rgba = bgra_to_rgba(rgba)
    else:
        raise ValueError(
            f"{path} uses unsupported TEX format ID 0x{header.format_id:02x}"
        )

    return header, rgba


def bgra_to_rgba(payload: bytes) -> bytes:
    output = bytearray(payload)
    output[0::4], output[2::4] = payload[2::4], payload[0::4]
    return bytes(output)


def require_texture2ddecoder(format_name: str) -> None:
    if texture2ddecoder is None:
        raise RuntimeError(
            f"{format_name} requires texture2ddecoder. "
            "Install with: python -m pip install texture2ddecoder"
        )


def iter_tex_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    else:
        yield from sorted(path.rglob("*.tex"))


def output_path_for(input_root: Path, output_root: Path, tex_path: Path) -> Path:
    if input_root.is_file():
        if output_root.suffix.lower() == ".png":
            return output_root
        return output_root / f"{tex_path.stem}.png"
    return output_root / tex_path.relative_to(input_root).with_suffix(".png")


def convert_one(input_root: Path, output_root: Path, tex_path: Path) -> dict:
    header, rgba = decode_tex(tex_path)
    png_path = output_path_for(input_root, output_root, tex_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGBA", (header.width, header.height), rgba).save(png_path)
    record = asdict(header)
    record["output"] = str(png_path)
    record["output_size"] = png_path.stat().st_size
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert GBM TEX files to PNG.")
    parser.add_argument("input", type=Path, help="Input .tex file or directory")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .png file or directory. Defaults to <input>_png for directories.",
    )
    parser.add_argument("--info", action="store_true", help="Print TEX header info only")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Write conversion manifest JSON. Defaults to <output>/_tex_manifest.json.",
    )
    args = parser.parse_args(argv)

    input_path = args.input
    output_path = args.output or Path(f"{input_path}_png")
    records = []
    failures = []

    for tex_path in iter_tex_files(input_path):
        try:
            if args.info:
                header = parse_header(tex_path)
                print(json.dumps(asdict(header), ensure_ascii=False))
                records.append(asdict(header))
            else:
                record = convert_one(input_path, output_path, tex_path)
                records.append(record)
                print(
                    f"{record['format_name']} {record['width']}x{record['height']} "
                    f"{tex_path} -> {record['output']}"
                )
        except Exception as exc:
            failures.append({"path": str(tex_path), "error": str(exc)})
            print(f"error: {tex_path}: {exc}", file=sys.stderr)

    if not args.info:
        output_path.mkdir(parents=True, exist_ok=True)
        manifest_path = args.manifest or output_path / "_tex_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "input": str(input_path),
                    "output": str(output_path),
                    "converted_count": len(records),
                    "failure_count": len(failures),
                    "records": records,
                    "failures": failures,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"manifest: {manifest_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
