#!/usr/bin/env python3
"""Extract Gundam Breaker Mobile ARCC v8 archives.

This handles the encrypted/compressed archive layout used by the Android
Gundam Breaker Mobile DLC files inspected in this workspace.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from Crypto.Cipher import Blowfish
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit(
        "Missing dependency: pycryptodome. Install with: python -m pip install pycryptodome"
    ) from exc


DEFAULT_KEY_HEX = "c6c8511ebdcae097fdb74684af51cfcd835fe0"
ENTRY_SIZE = 0x90
ENTRY_NAME_SIZE = 0x80
COMPRESSED_FLAG = 0x40000000
SIZE_MASK = 0x0FFFFFFF

MAGIC_EXTENSIONS = {
    b"IBMB": ".bmb",
    b"TEX ": ".tex",
    b"XFS\x00": ".xfs",
    b"EAN\x00": ".ean",
    b"EFL\x00": ".efl",
    b"GMD\x00": ".gmd",
    b"GUI\x00": ".gui",
    b"GFD\x00": ".gfd",
    b"FWSE": ".sew",
    b"OggS": ".ogg",
    b"BR3M": ".m3r",
    b"MFX\x00": ".mfx",
    b"PRPZ": ".prp",
    b"MOD\x00": ".mod",
    b"MRL\x00": ".mrl",
    b"LCM\x00": ".lcm",
    b"SDL\x00": ".sdl",
    b"LMT\x00": ".lmt",
    b"GLD\x00": ".gld",
    b"geo3": ".geo3",
    b"SBKR": ".sbkr",
    b"SRQR": ".srqr",
    b"SSQR": ".ssqr",
}

INVALID_PATH_CHARS = re.compile(r'[<>:"|?*]')


@dataclass(frozen=True)
class ArcEntry:
    index: int
    name: str
    type_code: int
    compressed_size: int
    size_flags: int
    uncompressed_size: int
    offset: int
    compressed: bool


def decrypt_mt_blowfish_swapped(cipher: Blowfish.BlowfishCipher, data: bytes) -> bytes:
    """Decrypt MT-style Blowfish blocks with 32-bit byte swaps around ECB."""

    if len(data) % 8 != 0:
        raise ValueError(f"encrypted payload length is not 8-byte aligned: {len(data)}")

    output = bytearray(len(data))
    for block_offset in range(0, len(data), 8):
        left, right = struct.unpack_from("<II", data, block_offset)
        swapped = struct.pack(">II", left, right)
        decrypted = cipher.decrypt(swapped)
        left_dec, right_dec = struct.unpack(">II", decrypted)
        struct.pack_into("<II", output, block_offset, left_dec, right_dec)
    return bytes(output)


def parse_header(archive_data: bytes) -> tuple[int, int]:
    if len(archive_data) < 8:
        raise ValueError("archive is too small for an ARCC header")

    magic, version, file_count = struct.unpack_from("<4sHH", archive_data, 0)
    if magic != b"ARCC":
        raise ValueError(f"unsupported archive magic {magic!r}; expected b'ARCC'")
    if version != 8:
        raise ValueError(f"unsupported ARCC version {version}; expected 8")
    return version, file_count


def parse_entries(toc: bytes, file_count: int) -> list[ArcEntry]:
    expected_size = file_count * ENTRY_SIZE
    if len(toc) != expected_size:
        raise ValueError(f"decrypted TOC size {len(toc)} != expected {expected_size}")

    entries: list[ArcEntry] = []
    for index in range(file_count):
        base = index * ENTRY_SIZE
        raw_name = toc[base : base + ENTRY_NAME_SIZE].split(b"\x00", 1)[0]
        name = raw_name.decode("utf-8", errors="replace")
        type_code, compressed_size, size_flags, offset = struct.unpack_from(
            "<IIII", toc, base + ENTRY_NAME_SIZE
        )
        entries.append(
            ArcEntry(
                index=index,
                name=name,
                type_code=type_code,
                compressed_size=compressed_size,
                size_flags=size_flags,
                uncompressed_size=size_flags & SIZE_MASK,
                offset=offset,
                compressed=bool(size_flags & COMPRESSED_FLAG),
            )
        )
    return entries


def infer_extension(payload: bytes) -> str:
    return MAGIC_EXTENSIONS.get(payload[:4], ".bin")


def safe_output_path(output_dir: Path, entry: ArcEntry, extension: str) -> Path:
    archive_name = entry.name.replace("\\", "/").strip("/")
    parts: list[str] = []
    for part in archive_name.split("/"):
        if not part or part in {".", ".."}:
            continue
        parts.append(INVALID_PATH_CHARS.sub("_", part))

    if not parts:
        parts = [f"entry_{entry.index:04d}"]

    leaf = Path(parts[-1])
    if not leaf.suffix:
        parts[-1] = f"{parts[-1]}{extension}"

    return output_dir.joinpath(*parts)


def extract_entry(
    archive_data: bytes,
    cipher: Blowfish.BlowfishCipher,
    entry: ArcEntry,
) -> tuple[bytes, str]:
    end = entry.offset + entry.compressed_size
    validate_entry_bounds(len(archive_data), entry)

    encrypted_payload = archive_data[entry.offset:end]
    decrypted_payload = decrypt_mt_blowfish_swapped(cipher, encrypted_payload)
    if entry.compressed:
        payload = zlib.decompress(decrypted_payload)
    else:
        payload = decrypted_payload[: entry.uncompressed_size or None]

    if entry.uncompressed_size and len(payload) != entry.uncompressed_size:
        raise ValueError(
            f"entry {entry.index} decompressed to {len(payload)} bytes, "
            f"expected {entry.uncompressed_size}"
        )

    return payload, infer_extension(payload)


def iter_limited(entries: Iterable[ArcEntry], limit: int | None) -> Iterable[ArcEntry]:
    for position, entry in enumerate(entries):
        if limit is not None and position >= limit:
            return
        yield entry


def load_archive(path: Path, key: bytes) -> tuple[bytes, list[ArcEntry]]:
    archive_data = path.read_bytes()
    _version, file_count = parse_header(archive_data)
    toc_size = file_count * ENTRY_SIZE
    encrypted_toc = archive_data[8 : 8 + toc_size]
    if len(encrypted_toc) != toc_size:
        raise ValueError(f"archive ended before TOC was complete: need {toc_size} bytes")

    cipher = Blowfish.new(key, Blowfish.MODE_ECB)
    toc = decrypt_mt_blowfish_swapped(cipher, encrypted_toc)
    return archive_data, parse_entries(toc, file_count)


def validate_entry_bounds(archive_size: int, entry: ArcEntry) -> None:
    end = entry.offset + entry.compressed_size
    if entry.offset < 0 or end > archive_size:
        raise ValueError(
            f"entry {entry.index} points outside archive: "
            f"offset=0x{entry.offset:x}, size=0x{entry.compressed_size:x}"
        )


def resolve_dump_decrypted_path(output: Path, archive: Path) -> Path:
    """Resolve a dump target to a concrete .arc file path.

    Existing directories, or paths ending in a path separator, are treated as
    output folders and receive ``<archive-stem>_decrypted.arc``.
    """

    output_text = str(output)
    if output.exists() and output.is_dir():
        return output / f"{archive.stem}_decrypted.arc"
    if output_text.endswith(("/", "\\")):
        return output / f"{archive.stem}_decrypted.arc"
    return output


def dump_decrypted_archive(
    archive_data: bytes,
    entries: list[ArcEntry],
    cipher: Blowfish.BlowfishCipher,
    output_path: Path,
) -> None:
    """Write a single ARCC file with Blowfish-decrypted TOC and payloads.

    Payloads keep their original zlib-compressed form; only the Blowfish layer
    is removed. The output archive preserves the input size and entry layout.
    """

    output = bytearray(archive_data)
    toc_size = len(entries) * ENTRY_SIZE
    encrypted_toc = bytes(output[8 : 8 + toc_size])
    output[8 : 8 + toc_size] = decrypt_mt_blowfish_swapped(cipher, encrypted_toc)

    for entry in entries:
        validate_entry_bounds(len(output), entry)
        start = entry.offset
        end = start + entry.compressed_size
        encrypted_payload = bytes(output[start:end])
        output[start:end] = decrypt_mt_blowfish_swapped(cipher, encrypted_payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Gundam Breaker Mobile ARCC v8 archives."
    )
    parser.add_argument("archive", type=Path, help="Path to an .arc file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory. Defaults to <archive stem>_extracted.",
    )
    parser.add_argument(
        "--key-hex",
        default=DEFAULT_KEY_HEX,
        help="Blowfish key bytes as hex. Defaults to the recovered GBM DLC key.",
    )
    parser.add_argument("--list-only", action="store_true", help="Print entries only")
    parser.add_argument("--limit", type=int, help="Only list/extract the first N entries")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Manifest JSON path. Defaults to <output>/_manifest.json when extracting.",
    )
    parser.add_argument(
        "--dump-decrypted",
        type=Path,
        metavar="OUTPUT",
        help=(
            "Write a single decrypted ARCC file. Pass a file path or an output "
            "directory (writes <archive-stem>_decrypted.arc). Blowfish layers are "
            "removed but zlib-compressed payloads are preserved."
        ),
    )
    args = parser.parse_args(argv)

    key = bytes.fromhex(args.key_hex)
    archive_data, entries = load_archive(args.archive, key)
    selected_entries = list(iter_limited(entries, args.limit))

    if args.list_only:
        for entry in selected_entries:
            print(
                f"{entry.index:04d} "
                f"offset=0x{entry.offset:08x} "
                f"zsize=0x{entry.compressed_size:08x} "
                f"usize=0x{entry.uncompressed_size:08x} "
                f"type=0x{entry.type_code:08x} "
                f"{entry.name}"
            )
        return 0

    if args.dump_decrypted:
        dump_path = resolve_dump_decrypted_path(args.dump_decrypted, args.archive)
        cipher = Blowfish.new(key, Blowfish.MODE_ECB)
        dump_decrypted_archive(archive_data, entries, cipher, dump_path)
        print(
            f"dumped decrypted archive: {len(entries)} entries, "
            f"{len(archive_data)} bytes -> {dump_path}"
        )
        return 0

    output_dir = args.output or Path(f"{args.archive.stem}_extracted")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "archive": str(args.archive),
        "file_count": len(entries),
        "extracted_count": len(selected_entries),
        "entries": [],
    }

    cipher = Blowfish.new(key, Blowfish.MODE_ECB)
    for entry in selected_entries:
        payload, extension = extract_entry(archive_data, cipher, entry)
        output_path = safe_output_path(output_dir, entry, extension)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)

        record = asdict(entry)
        record.update(
            {
                "extension": extension,
                "magic": payload[:4].hex(" "),
                "output": str(output_path),
                "output_size": len(payload),
            }
        )
        manifest["entries"].append(record)

    manifest_path = args.manifest or output_dir / "_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(
        f"extracted {len(selected_entries)} / {len(entries)} entries "
        f"from {args.archive} to {output_dir}"
    )
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
