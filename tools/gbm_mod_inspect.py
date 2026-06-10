#!/usr/bin/env python3
"""Inspect Gundam Breaker Mobile MOD v7 model containers.

This is a read-only structural inspector. It follows the layout observed in
GBM's ``rModel::load`` path: a 0xa0-byte header and a primitive table made of
0x38-byte records. It does not yet decode the packed vertex attributes into
geometry.
"""

from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


HEADER_SIZE = 0xA0
PRIMITIVE_RECORD_SIZE = 0x38
PRIMITIVE_RECORD_PREFIX = "<HHIHBB6I"
MATERIAL_BIND_RECORD_SIZE = 0x90


@dataclass(frozen=True)
class ModHeader:
    path: str
    file_size: int
    version: int
    bone_count: int
    primitive_count: int
    material_name_count: int
    vertex_count_field: int
    index_count_field: int
    triangle_count_field: int
    vertex_buffer_size_field: int
    aux20_record_count: int
    aux24_record_count: int
    bone_section_offset: int
    aux20_offset: int
    material_name_offset: int
    primitive_offset: int
    vertex_buffer_offset: int
    index_buffer_offset: int
    unknown_offset_58: int
    bounds_floats_60: list[float]


@dataclass(frozen=True)
class PrimitiveRecord:
    index: int
    offset: int
    sentinel: int
    vertex_count: int
    packed_flags: int
    draw_mode_or_flags: int
    vertex_size: int
    vertex_type: int
    vertex_start: int
    vertex_base_offset: int
    resource_hash_or_key: int
    index_start: int
    index_count: int
    field_20: int
    field_24: int
    material_table_index: int
    group_id: int
    vertex_range_start: int
    vertex_range_end: int
    field_2c: int
    runtime_pointer_slot: int
    vertex_byte_start: int
    vertex_byte_end: int
    index_byte_start: int
    index_byte_end: int
    valid_ranges: bool


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def parse_header(path: Path, data: bytes) -> ModHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"{path} is too small for a MOD v7 header")
    magic = data[:4]
    if magic != b"MOD\x00":
        raise ValueError(f"{path} does not start with MOD magic")

    version, bone_count, primitive_count, material_name_count = struct.unpack_from(
        "<4H", data, 4
    )
    vertex_count, index_count, triangle_count, vertex_buffer_size = struct.unpack_from(
        "<4I", data, 0x0C
    )
    aux20_record_count, aux24_record_count = struct.unpack_from("<2I", data, 0x20)

    return ModHeader(
        path=str(path),
        file_size=len(data),
        version=version,
        bone_count=bone_count,
        primitive_count=primitive_count,
        material_name_count=material_name_count,
        vertex_count_field=vertex_count,
        index_count_field=index_count,
        triangle_count_field=triangle_count,
        vertex_buffer_size_field=vertex_buffer_size,
        aux20_record_count=aux20_record_count,
        aux24_record_count=aux24_record_count,
        bone_section_offset=read_u64(data, 0x28),
        aux20_offset=read_u64(data, 0x30),
        material_name_offset=read_u64(data, 0x38),
        primitive_offset=read_u64(data, 0x40),
        vertex_buffer_offset=read_u64(data, 0x48),
        index_buffer_offset=read_u64(data, 0x50),
        unknown_offset_58=read_u64(data, 0x58),
        bounds_floats_60=list(struct.unpack_from("<12f", data, 0x60)),
    )


def parse_primitive_record(
    data: bytes,
    header: ModHeader,
    index: int,
    offset: int,
) -> PrimitiveRecord:
    (
        sentinel,
        vertex_count,
        packed_flags,
        draw_mode_or_flags,
        vertex_size,
        vertex_type,
        vertex_start,
        vertex_base_offset,
        resource_hash_or_key,
        index_start,
        index_count,
        field_20,
    ) = struct.unpack_from(PRIMITIVE_RECORD_PREFIX, data, offset)

    field_24 = data[offset + 0x24]
    material_table_index = data[offset + 0x25]
    group_id = struct.unpack_from("<H", data, offset + 0x26)[0]
    vertex_range_start, vertex_range_end = struct.unpack_from("<2H", data, offset + 0x28)
    field_2c = read_u32(data, offset + 0x2C)
    runtime_pointer_slot = read_u64(data, offset + 0x30)

    vertex_byte_start = (
        header.vertex_buffer_offset + vertex_base_offset + vertex_start * max(vertex_size, 1)
    )
    vertex_byte_end = vertex_byte_start + vertex_count * max(vertex_size, 1)
    index_byte_start = header.index_buffer_offset + index_start * 2
    index_byte_end = index_byte_start + index_count * 2

    valid_ranges = (
        vertex_count > 0
        and vertex_size > 0
        and header.vertex_buffer_offset
        <= vertex_byte_start
        <= vertex_byte_end
        <= header.index_buffer_offset
        and header.index_buffer_offset
        <= index_byte_start
        <= index_byte_end
        <= header.file_size
    )

    return PrimitiveRecord(
        index=index,
        offset=offset,
        sentinel=sentinel,
        vertex_count=vertex_count,
        packed_flags=packed_flags,
        draw_mode_or_flags=draw_mode_or_flags,
        vertex_size=vertex_size,
        vertex_type=vertex_type,
        vertex_start=vertex_start,
        vertex_base_offset=vertex_base_offset,
        resource_hash_or_key=resource_hash_or_key,
        index_start=index_start,
        index_count=index_count,
        field_20=field_20,
        field_24=field_24,
        material_table_index=material_table_index,
        group_id=group_id,
        vertex_range_start=vertex_range_start,
        vertex_range_end=vertex_range_end,
        field_2c=field_2c,
        runtime_pointer_slot=runtime_pointer_slot,
        vertex_byte_start=vertex_byte_start,
        vertex_byte_end=vertex_byte_end,
        index_byte_start=index_byte_start,
        index_byte_end=index_byte_end,
        valid_ranges=valid_ranges,
    )


def read_material_names(data: bytes, header: ModHeader) -> list[str]:
    """Read the MOD material name table (0x80 bytes per name)."""
    names: list[str] = []
    for index in range(header.material_name_count):
        start = header.material_name_offset + index * 0x80
        names.append(data[start : start + 0x80].split(b"\x00", 1)[0].decode("ascii"))
    return names


def parse_primitive_records(data: bytes, header: ModHeader) -> list[PrimitiveRecord]:
    records: list[PrimitiveRecord] = []
    table_bytes = header.primitive_count * PRIMITIVE_RECORD_SIZE
    table_end = header.primitive_offset + table_bytes
    if table_end > len(data):
        raise ValueError(
            f"primitive table ends at 0x{table_end:x}, beyond file size 0x{len(data):x}"
        )

    for index in range(header.primitive_count):
        offset = header.primitive_offset + index * PRIMITIVE_RECORD_SIZE
        records.append(parse_primitive_record(data, header, index, offset))
    return records


def build_section_layout(data: bytes, header: ModHeader) -> dict[str, Any]:
    bone_section_size = (
        header.bone_count * 24
        + header.bone_count * 64
        + header.bone_count * 64
        + 0x1000
        + header.aux24_record_count * 36
    )
    primitive_table_size = header.primitive_count * PRIMITIVE_RECORD_SIZE
    material_name_table_size = header.material_name_count * 0x80
    primitive_table_end = header.primitive_offset + primitive_table_size
    material_bind_count = (
        read_u32(data, primitive_table_end)
        if primitive_table_end + 4 <= header.vertex_buffer_offset
        else None
    )
    material_bind_table_size = (
        material_bind_count * MATERIAL_BIND_RECORD_SIZE
        if material_bind_count is not None
        else None
    )

    return {
        "header": {"start": 0, "end": HEADER_SIZE, "size": HEADER_SIZE},
        "bone_section": {
            "start": header.bone_section_offset,
            "end": header.bone_section_offset + bone_section_size,
            "size": bone_section_size,
            "matches_aux20_offset": header.bone_section_offset + bone_section_size
            == header.aux20_offset,
        },
        "aux20_table": {
            "start": header.aux20_offset,
            "end": header.aux20_offset + header.aux20_record_count * 0x20,
            "size": header.aux20_record_count * 0x20,
            "record_count": header.aux20_record_count,
            "record_size": 0x20,
            "matches_material_name_offset": header.aux20_offset
            + header.aux20_record_count * 0x20
            == header.material_name_offset,
        },
        "material_name_table": {
            "start": header.material_name_offset,
            "end": header.material_name_offset + material_name_table_size,
            "size": material_name_table_size,
            "record_count": header.material_name_count,
            "record_size": 0x80,
            "matches_primitive_offset": header.material_name_offset
            + material_name_table_size
            == header.primitive_offset,
        },
        "primitive_table": {
            "start": header.primitive_offset,
            "end": primitive_table_end,
            "size": primitive_table_size,
            "record_count": header.primitive_count,
            "record_size": PRIMITIVE_RECORD_SIZE,
        },
        "material_bind_table": {
            "count_offset": primitive_table_end,
            "record_start": primitive_table_end + 4,
            "record_end": primitive_table_end + 4 + (material_bind_table_size or 0),
            "record_count": material_bind_count,
            "record_size": MATERIAL_BIND_RECORD_SIZE,
            "size": material_bind_table_size,
            "matches_vertex_buffer_offset": material_bind_count is not None
            and primitive_table_end + 4 + material_bind_table_size
            == header.vertex_buffer_offset,
        },
        "vertex_buffer": {
            "start": header.vertex_buffer_offset,
            "end": header.index_buffer_offset,
            "size": header.index_buffer_offset - header.vertex_buffer_offset,
            "matches_header_field": header.index_buffer_offset
            - header.vertex_buffer_offset
            == header.vertex_buffer_size_field,
        },
        "index_buffer": {
            "start": header.index_buffer_offset,
            "end": header.file_size,
            "size": header.file_size - header.index_buffer_offset,
            "header_count_field": header.index_count_field,
            "header_count_bytes": header.index_count_field * 2,
            "header_count_end": header.index_buffer_offset + header.index_count_field * 2,
        },
    }


def summarize_records(
    data: bytes, header: ModHeader, records: list[PrimitiveRecord]
) -> dict[str, int | bool]:
    valid_records = [record for record in records if record.valid_ranges]
    total_record_vertices = sum(record.vertex_count for record in valid_records)
    total_record_indices = sum(record.index_count for record in valid_records)
    total_strip_triangles = sum(
        count_triangle_strip_faces(data, header, record) for record in valid_records
    )
    max_vertex_byte_end = max((record.vertex_byte_end for record in valid_records), default=0)
    max_index_byte_end = max((record.index_byte_end for record in valid_records), default=0)

    return {
        "parsed_primitive_records": len(records),
        "valid_primitive_records": len(valid_records),
        "total_record_vertices": total_record_vertices,
        "total_record_indices": total_record_indices,
        "total_strip_triangles": total_strip_triangles,
        "vertex_record_sum_matches_header": total_record_vertices
        == header.vertex_count_field,
        "triangle_strip_count_matches_header": total_strip_triangles
        == header.triangle_count_field,
        "index_record_sum_delta_to_header": header.index_count_field
        - total_record_indices,
        "max_vertex_byte_end": max_vertex_byte_end,
        "max_index_byte_end": max_index_byte_end,
        "vertex_buffer_span_matches_header": max_vertex_byte_end
        == header.index_buffer_offset,
        "index_field_byte_end_delta_to_file": header.file_size
        - (header.index_buffer_offset + header.index_count_field * 2),
        "max_index_byte_end_delta_to_file": header.file_size - max_index_byte_end,
    }


def count_triangle_strip_faces(
    data: bytes, header: ModHeader, record: PrimitiveRecord
) -> int:
    if record.index_count < 3:
        return 0

    indices = struct.unpack_from(
        f"<{record.index_count}H",
        data,
        header.index_buffer_offset + record.index_start * 2,
    )
    reverse = True
    face_count = 0
    f1, f2 = indices[0], indices[1]
    for f3 in indices[2:]:
        if f3 == 0xFFFF:
            reverse = True
            f1 = f2 = 0xFFFF
            continue

        reverse = not reverse
        if (
            f1 != 0xFFFF
            and f2 != 0xFFFF
            and f1 != f2
            and f2 != f3
            and f3 != f1
        ):
            face_count += 1
        f1, f2 = f2, f3
    return face_count


def inspect_mod(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    header = parse_header(path, data)
    primitive_records = parse_primitive_records(data, header)
    valid_records = [record for record in primitive_records if record.valid_ranges]

    report: dict[str, Any] = {
        "header": asdict(header),
        "material_names": read_material_names(data, header),
        "section_layout": build_section_layout(data, header),
        "primitive_record_size": PRIMITIVE_RECORD_SIZE,
        "summary": summarize_records(data, header, primitive_records),
        "vertex_size_counts": dict(Counter(record.vertex_size for record in valid_records)),
        "vertex_type_counts": dict(Counter(record.vertex_type for record in valid_records)),
        "material_table_index_counts": dict(
            Counter(record.material_table_index for record in valid_records)
        ),
        "primitive_records": [asdict(record) for record in primitive_records],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect GBM MOD v7 model structure.")
    parser.add_argument("mod", type=Path, help="Input .mod file")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON report")
    args = parser.parse_args()

    report = inspect_mod(args.mod)
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
