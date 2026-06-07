#!/usr/bin/env python3
"""Inspect GBM's MT Framework MFX shader package input layouts."""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MFX_MAGIC = b"MFX\x00"
OBJECT_TABLE_OFFSET = 0x28
INPUT_LAYOUT_TYPE = 6
INPUT_ELEMENT_SIZE = 0x10

FORMAT_NAMES = {
    1: "FLOAT32",
    2: "S16_FIXED_10",
    3: "S16",
    4: "U16",
    5: "SNORM16",
    6: "UNORM16",
    7: "S8",
    8: "U8",
    9: "SNORM8",
    10: "UNORM8",
    11: "PACKED",
}

FORMAT_SIZES = {
    1: 4,
    2: 2,
    3: 2,
    4: 2,
    5: 2,
    6: 2,
    7: 1,
    8: 1,
    9: 1,
    10: 1,
    11: 4,
}


@dataclass(frozen=True)
class InputElement:
    semantic: str
    semantic_index: int
    format_id: int
    format_name: str
    component_count: int
    byte_offset: int
    byte_size: int
    packed: int


@dataclass(frozen=True)
class InputLayout:
    index: int
    name: str
    object_offset: int
    object_type: int
    element_count: int
    stored_stride: int
    calculated_stride: int
    elements: list[InputElement]


@dataclass(frozen=True)
class MfxHeader:
    path: str
    file_size: int
    version_field: int
    object_count: int
    count_10: int
    count_14: int
    count_18: int
    string_table_offset: int


def read_c_string(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError(f"string offset 0x{offset:x} is outside file")
    end = data.find(b"\x00", offset)
    if end < 0:
        raise ValueError(f"unterminated string at 0x{offset:x}")
    return data[offset:end].decode("ascii", errors="replace")


def parse_mfx_header(path: Path, data: bytes) -> MfxHeader:
    if len(data) < OBJECT_TABLE_OFFSET:
        raise ValueError(f"{path} is too small for an MFX header")
    if data[:4] != MFX_MAGIC:
        raise ValueError(f"{path} does not start with MFX magic")

    return MfxHeader(
        path=str(path),
        file_size=len(data),
        version_field=struct.unpack_from("<I", data, 4)[0],
        object_count=struct.unpack_from("<I", data, 0x0C)[0],
        count_10=struct.unpack_from("<I", data, 0x10)[0],
        count_14=struct.unpack_from("<I", data, 0x14)[0],
        count_18=struct.unpack_from("<I", data, 0x18)[0],
        string_table_offset=struct.unpack_from("<Q", data, 0x20)[0],
    )


def parse_input_layouts(path: Path) -> tuple[MfxHeader, dict[int, InputLayout]]:
    data = path.read_bytes()
    header = parse_mfx_header(path, data)
    table_end = OBJECT_TABLE_OFFSET + header.object_count * 8
    if table_end > len(data):
        raise ValueError("MFX object table extends beyond the file")

    object_offsets = struct.unpack_from(
        f"<{header.object_count}Q", data, OBJECT_TABLE_OFFSET
    )
    layouts: dict[int, InputLayout] = {}
    for index, object_offset in enumerate(object_offsets):
        if object_offset == 0:
            continue
        if object_offset + 0x38 > header.string_table_offset:
            continue

        object_type = struct.unpack_from("<I", data, object_offset + 0x10)[0] & 0x3F
        if object_type != INPUT_LAYOUT_TYPE:
            continue

        name_relative = struct.unpack_from("<Q", data, object_offset)[0]
        name = read_c_string(data, header.string_table_offset + name_relative)
        element_count, stored_stride = struct.unpack_from(
            "<2H", data, object_offset + 0x28
        )
        elements: list[InputElement] = []
        calculated_stride = 0
        for element_index in range(element_count):
            element_offset = object_offset + 0x38 + element_index * INPUT_ELEMENT_SIZE
            if element_offset + INPUT_ELEMENT_SIZE > len(data):
                raise ValueError(f"layout {index} element table exceeds file")
            semantic_relative, packed = struct.unpack_from("<QI", data, element_offset)
            semantic = read_c_string(
                data, header.string_table_offset + semantic_relative
            )
            semantic_index = packed & 0x3F
            format_id = (packed >> 6) & 0x1F
            component_count = (packed >> 11) & 0x7F
            byte_offset = (packed >> 18) & 0x3FFF
            byte_size = FORMAT_SIZES.get(format_id, 0) * component_count
            calculated_stride = max(calculated_stride, byte_offset + byte_size)
            elements.append(
                InputElement(
                    semantic=semantic,
                    semantic_index=semantic_index,
                    format_id=format_id,
                    format_name=FORMAT_NAMES.get(format_id, f"UNKNOWN_{format_id}"),
                    component_count=component_count,
                    byte_offset=byte_offset,
                    byte_size=byte_size,
                    packed=packed,
                )
            )

        calculated_stride = (calculated_stride + 3) & ~3
        layouts[index] = InputLayout(
            index=index,
            name=name,
            object_offset=object_offset,
            object_type=object_type,
            element_count=element_count,
            stored_stride=stored_stride,
            calculated_stride=calculated_stride,
            elements=elements,
        )

    return header, layouts


def inspect_mfx(path: Path) -> dict[str, Any]:
    header, layouts = parse_input_layouts(path)
    return {
        "header": asdict(header),
        "input_layout_count": len(layouts),
        "stride_mismatch_count": sum(
            layout.stored_stride != layout.calculated_stride
            for layout in layouts.values()
        ),
        "input_layouts": {
            str(index): asdict(layout) for index, layout in layouts.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect GBM MFX input layouts.")
    parser.add_argument("mfx", type=Path, help="Input ShaderPackage.mfx")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON report")
    args = parser.parse_args()

    report = inspect_mfx(args.mfx)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
