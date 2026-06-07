#!/usr/bin/env python3
"""Export a GBM MOD v7 static bind-pose OBJ.

The geometry path is evidence-based:

* primitive and index layout comes from ``rModel::load``;
* vertex attributes come from ``ShaderPackage.mfx`` input layouts;
* quantized positions are decoded through the two bone matrix arrays.

Bone weights are inspected but OBJ cannot preserve a skeleton, so this remains
a static bind-pose export. Use the Blender conversion helper for FBX output.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Sequence

from gbm_mfx_inspect import InputElement, InputLayout, parse_input_layouts
from gbm_mod_inspect import ModHeader, PrimitiveRecord, parse_header, parse_primitive_records


Matrix4 = tuple[tuple[float, float, float, float], ...]
DEFAULT_MFX = Path(__file__).resolve().parent / "ShaderPackage.mfx"


def matrix_from_bytes(data: bytes, offset: int) -> Matrix4:
    values = struct.unpack_from("<16f", data, offset)
    return tuple(
        tuple(float(values[row * 4 + column]) for column in range(4))
        for row in range(4)
    )


def multiply_matrix(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(
            sum(left[row][axis] * right[axis][column] for axis in range(4))
            for column in range(4)
        )
        for row in range(4)
    )


def transform_row_vector(vector: Sequence[float], matrix: Matrix4) -> tuple[float, ...]:
    return tuple(
        sum(vector[axis] * matrix[axis][column] for axis in range(4))
        for column in range(4)
    )


def max_matrix_delta(left: Matrix4, right: Matrix4) -> float:
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def derive_bind_decode_matrix(
    data: bytes, header: ModHeader
) -> tuple[Matrix4, float, list[int]]:
    bone_info_offset = header.bone_section_offset
    local_matrix_offset = bone_info_offset + header.bone_count * 24
    decode_matrix_offset = local_matrix_offset + header.bone_count * 64
    parents = [
        data[bone_info_offset + bone_index * 24 + 2]
        for bone_index in range(header.bone_count)
    ]
    local_matrices = [
        matrix_from_bytes(data, local_matrix_offset + bone_index * 64)
        for bone_index in range(header.bone_count)
    ]
    decode_matrices = [
        matrix_from_bytes(data, decode_matrix_offset + bone_index * 64)
        for bone_index in range(header.bone_count)
    ]

    world_matrices: list[Matrix4] = []
    for bone_index, local_matrix in enumerate(local_matrices):
        parent = parents[bone_index]
        if parent == 0xFF:
            world_matrices.append(local_matrix)
        else:
            if parent >= bone_index:
                raise ValueError(
                    f"bone {bone_index} has unsupported parent index {parent}"
                )
            world_matrices.append(
                multiply_matrix(local_matrix, world_matrices[parent])
            )

    products = [
        multiply_matrix(decode_matrices[index], world_matrices[index])
        for index in range(header.bone_count)
    ]
    bind_decode_matrix = products[0]
    maximum_delta = max(
        max_matrix_delta(bind_decode_matrix, matrix) for matrix in products
    )
    return bind_decode_matrix, maximum_delta, parents


def parse_bone_palettes(data: bytes, header: ModHeader) -> list[list[int]]:
    palette_offset = (
        header.bone_section_offset
        + header.bone_count * 24
        + header.bone_count * 64
        + header.bone_count * 64
        + 0x1000
    )
    palettes: list[list[int]] = []
    for palette_index in range(header.aux24_record_count):
        record_offset = palette_offset + palette_index * 36
        count = struct.unpack_from("<I", data, record_offset)[0]
        if count > 32:
            raise ValueError(f"bone palette {palette_index} has invalid count {count}")
        palettes.append(list(data[record_offset + 4 : record_offset + 4 + count]))
    return palettes


def iter_strip_faces(
    indices: list[int], vertex_start: int
) -> Iterable[tuple[int, int, int]]:
    if len(indices) < 3:
        return

    reverse = True
    pos = 2
    f1, f2 = indices[0], indices[1]
    while pos < len(indices):
        f3 = indices[pos]
        pos += 1
        if f3 == 0xFFFF:
            reverse = True
            if pos + 1 >= len(indices):
                break
            f1, f2 = indices[pos], indices[pos + 1]
            pos += 2
            continue

        reverse = not reverse
        if (
            f1 != 0xFFFF
            and f2 != 0xFFFF
            and f1 != f2
            and f2 != f3
            and f3 != f1
        ):
            a = f1 - vertex_start
            b = f2 - vertex_start
            c = f3 - vertex_start
            yield (a, c, b) if reverse else (a, b, c)
        f1, f2 = f2, f3


def collect_raw_position_bounds(
    data: bytes,
    header: ModHeader,
    records: list[PrimitiveRecord],
    layouts: dict[int, InputLayout],
) -> tuple[list[int], list[int]]:
    mins = [0x7FFF, 0x7FFF, 0x7FFF]
    maxs = [-0x8000, -0x8000, -0x8000]
    for record in records:
        layout = layouts[record.resource_hash_or_key & 0xFFF]
        position = find_element(layout, "Position")
        start = header.vertex_buffer_offset + record.vertex_base_offset + (
            record.vertex_start * record.vertex_size
        )
        for index in range(record.vertex_count):
            raw = struct.unpack_from(
                "<3h",
                data,
                start + index * record.vertex_size + position.byte_offset,
            )
            for channel, value in enumerate(raw):
                mins[channel] = min(mins[channel], value)
                maxs[channel] = max(maxs[channel], value)
    return mins, maxs


def find_element(layout: InputLayout, semantic: str) -> InputElement:
    for element in layout.elements:
        if element.semantic == semantic:
            return element
    raise ValueError(f"layout {layout.index} ({layout.name}) lacks {semantic}")


def decode_element(raw_vertex: bytes, element: InputElement) -> tuple[float, ...]:
    offset = element.byte_offset
    count = element.component_count
    if element.format_id == 2:
        values = struct.unpack_from(f"<{count}h", raw_vertex, offset)
        return tuple(value / 1024.0 for value in values)
    if element.format_id == 5:
        values = struct.unpack_from(f"<{count}h", raw_vertex, offset)
        return tuple(max(-1.0, value / 32767.0) for value in values)
    if element.format_id == 8:
        return tuple(float(value) for value in raw_vertex[offset : offset + count])
    if element.format_id == 9:
        values = struct.unpack_from(f"<{count}b", raw_vertex, offset)
        return tuple(max(-1.0, value / 127.0) for value in values)
    if element.format_id == 10:
        values = raw_vertex[offset : offset + count]
        return tuple(value / 255.0 for value in values)
    raise ValueError(
        f"unsupported format {element.format_id} for {element.semantic}"
    )


def axis_transform(
    value: tuple[float, float, float], axis_mode: str
) -> tuple[float, float, float]:
    if axis_mode == "engine":
        return value
    if axis_mode == "blender":
        return (value[0], -value[2], value[1])
    raise ValueError(f"unsupported axis mode: {axis_mode}")


def is_lod_triplet(records: list[PrimitiveRecord]) -> bool:
    """Return True when three primitives look like high/medium/low LOD variants."""

    if len(records) != 3:
        return False

    sorted_records = sorted(records, key=lambda record: record.group_id)
    group_ids = [record.group_id for record in sorted_records]
    if group_ids != [1, 2, 3]:
        return False

    vertex_counts = [record.vertex_count for record in sorted_records]
    return vertex_counts[0] > vertex_counts[1] > vertex_counts[2]


def select_primitives_for_lod(
    records: list[PrimitiveRecord], lod: int
) -> list[PrimitiveRecord]:
    """Keep one LOD variant per material group, or all parts when no LOD chain exists."""

    grouped: dict[int, list[PrimitiveRecord]] = {}
    for record in records:
        grouped.setdefault(record.material_table_index, []).append(record)

    selected: list[PrimitiveRecord] = []
    for material_records in grouped.values():
        if is_lod_triplet(material_records):
            target_group_id = lod + 1
            match = next(
                (
                    record
                    for record in material_records
                    if record.group_id == target_group_id
                ),
                None,
            )
            if match is None:
                material_index = material_records[0].material_table_index
                raise ValueError(
                    f"LOD {lod} is unavailable for material {material_index}"
                )
            selected.append(match)
        else:
            selected.extend(material_records)

    return sorted(selected, key=lambda record: record.index)


def decode_position(
    raw_position: tuple[float, float, float],
    header: ModHeader,
    raw_mins: list[int],
    raw_maxs: list[int],
    bind_decode_matrix: Matrix4,
    mode: str,
) -> tuple[float, float, float]:
    if mode == "bind-pose":
        result = transform_row_vector((*raw_position, 1.0), bind_decode_matrix)
        return (result[0], result[1], result[2])
    if mode == "raw-snorm16":
        return raw_position

    bounds_min = header.bounds_floats_60[4:7]
    bounds_max = header.bounds_floats_60[8:11]
    if mode == "observed-bounds":
        output = []
        for channel in range(3):
            raw_integer = round(raw_position[channel] * 32767.0)
            span = raw_maxs[channel] - raw_mins[channel]
            output.append(
                bounds_min[channel]
                if span == 0
                else bounds_min[channel]
                + ((raw_integer - raw_mins[channel]) / span)
                * (bounds_max[channel] - bounds_min[channel])
            )
        return tuple(output)
    raise ValueError(f"unsupported position mode: {mode}")


def write_mtl(obj_path: Path, texture_path: Path) -> Path:
    mtl_path = obj_path.with_suffix(".mtl")
    texture_relative = os.path.relpath(texture_path, mtl_path.parent).replace("\\", "/")
    mtl_path.write_text(
        "\n".join(
            (
                "newmtl gbm_material",
                "Ka 0.000000 0.000000 0.000000",
                "Kd 1.000000 1.000000 1.000000",
                "Ks 0.000000 0.000000 0.000000",
                "d 1.000000",
                "illum 1",
                f"map_Kd {texture_relative}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return mtl_path


def write_obj_probe(
    mod_path: Path,
    mfx_path: Path,
    obj_path: Path,
    manifest_path: Path | None,
    position_mode: str,
    axis_mode: str,
    texture_path: Path | None,
    lod: int = 0,
) -> dict:
    data = mod_path.read_bytes()
    header = parse_header(mod_path, data)
    all_records = parse_primitive_records(data, header)
    records = select_primitives_for_lod(all_records, lod)
    _, layouts = parse_input_layouts(mfx_path)
    used_layout_ids = sorted(
        {record.resource_hash_or_key & 0xFFF for record in records}
    )
    missing_layout_ids = [
        layout_id for layout_id in used_layout_ids if layout_id not in layouts
    ]
    if missing_layout_ids:
        raise ValueError(f"MFX is missing layouts {missing_layout_ids}")
    for record in records:
        layout = layouts[record.resource_hash_or_key & 0xFFF]
        if layout.stored_stride != record.vertex_size:
            raise ValueError(
                f"primitive {record.index} stride {record.vertex_size} "
                f"does not match layout {layout.index} stride {layout.stored_stride}"
            )

    bind_decode_matrix, bind_matrix_max_delta, parents = derive_bind_decode_matrix(
        data, header
    )
    bone_palettes = parse_bone_palettes(data, header)
    raw_mins, raw_maxs = collect_raw_position_bounds(
        data, header, records, layouts
    )

    obj_path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = write_mtl(obj_path, texture_path) if texture_path else None
    total_vertices = 0
    total_faces = 0
    out_of_range_faces = 0
    decoded_bounds_min = [math.inf, math.inf, math.inf]
    decoded_bounds_max = [-math.inf, -math.inf, -math.inf]

    with obj_path.open("w", encoding="utf-8", newline="\n") as obj:
        obj.write("# GBM MOD v7 static bind-pose OBJ\n")
        obj.write(f"# source: {mod_path}\n")
        obj.write(f"# mfx: {mfx_path}\n")
        obj.write(f"# position_mode: {position_mode}\n")
        obj.write(f"# axis_mode: {axis_mode}\n")
        obj.write(f"# lod: {lod}\n")
        if mtl_path:
            obj.write(f"mtllib {mtl_path.name}\n")
            obj.write("usemtl gbm_material\n")

        global_vertex_base = 1
        for record in records:
            layout_id = record.resource_hash_or_key & 0xFFF
            layout = layouts[layout_id]
            position_element = find_element(layout, "Position")
            normal_element = find_element(layout, "Normal")
            uv_element = find_element(layout, "TexCoord")
            obj.write(
                f"\ng primitive_{record.index:03d}_layout_{layout_id}_{layout.name}\n"
            )
            vertex_start = header.vertex_buffer_offset + record.vertex_base_offset + (
                record.vertex_start * record.vertex_size
            )
            for vertex_index in range(record.vertex_count):
                vertex_bytes = data[
                    vertex_start
                    + vertex_index * record.vertex_size : vertex_start
                    + (vertex_index + 1) * record.vertex_size
                ]
                raw_position = decode_element(vertex_bytes, position_element)[:3]
                engine_position = decode_position(
                    raw_position,
                    header,
                    raw_mins,
                    raw_maxs,
                    bind_decode_matrix,
                    position_mode,
                )
                position = axis_transform(engine_position, axis_mode)
                raw_uv = decode_element(vertex_bytes, uv_element)[:2]
                uv = (raw_uv[0], 1.0 - raw_uv[1])
                engine_normal = decode_element(vertex_bytes, normal_element)[:3]
                normal = axis_transform(engine_normal, axis_mode)
                normal_length = math.sqrt(sum(component * component for component in normal))
                if normal_length > 0:
                    normal = tuple(component / normal_length for component in normal)

                for channel in range(3):
                    decoded_bounds_min[channel] = min(
                        decoded_bounds_min[channel], position[channel]
                    )
                    decoded_bounds_max[channel] = max(
                        decoded_bounds_max[channel], position[channel]
                    )
                obj.write(
                    f"v {position[0]:.6f} {position[1]:.6f} {position[2]:.6f}\n"
                )
                obj.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
                obj.write(
                    f"vn {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n"
                )

            index_offset = header.index_buffer_offset + record.index_start * 2
            indices = list(
                struct.unpack_from(f"<{record.index_count}H", data, index_offset)
            )
            for face in iter_strip_faces(indices, record.vertex_start):
                if any(index < 0 or index >= record.vertex_count for index in face):
                    out_of_range_faces += 1
                    continue
                a, b, c = (global_vertex_base + index for index in face)
                obj.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
                total_faces += 1

            total_vertices += record.vertex_count
            global_vertex_base += record.vertex_count

    used_layouts = {
        str(layout_id): asdict(layouts[layout_id]) for layout_id in used_layout_ids
    }
    manifest = {
        "source": str(mod_path),
        "mfx": str(mfx_path),
        "obj": str(obj_path),
        "mtl": str(mtl_path) if mtl_path else None,
        "texture": str(texture_path) if texture_path else None,
        "position_mode": position_mode,
        "axis_mode": axis_mode,
        "lod": lod,
        "primitive_count_total": len(all_records),
        "primitive_count_exported": len(records),
        "exported_primitive_indices": [record.index for record in records],
        "export_scope": "static bind-pose mesh; skeleton/weights are not represented by OBJ",
        "header": asdict(header),
        "used_input_layouts": used_layouts,
        "bind_decode_matrix": bind_decode_matrix,
        "bind_matrix_max_delta": bind_matrix_max_delta,
        "bone_parents": parents,
        "bone_palettes": bone_palettes,
        "raw_position_mins": raw_mins,
        "raw_position_maxs": raw_maxs,
        "decoded_bounds_min": decoded_bounds_min,
        "decoded_bounds_max": decoded_bounds_max,
        "primitive_count": len(records),
        "vertices": total_vertices,
        "faces": total_faces,
        "out_of_range_faces": out_of_range_faces,
        "matches_header_vertices": total_vertices == header.vertex_count_field,
        "matches_header_triangles": total_faces == header.triangle_count_field,
    }

    if manifest_path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def resolve_obj_output_path(mod_path: Path, output_path: Path) -> Path:
    """Allow -o to be either an OBJ file path or an output directory."""

    if output_path.suffix.lower() == ".obj":
        return output_path
    if output_path.exists() and output_path.is_file():
        raise ValueError(
            f"Output path exists and is not an .obj file: {output_path}"
        )
    return output_path / f"{mod_path.stem}.obj"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a GBM MOD v7 static bind-pose OBJ."
    )
    parser.add_argument("mod", type=Path, help="Input .mod file")
    parser.add_argument(
        "--mfx",
        type=Path,
        default=DEFAULT_MFX,
        help=f"ShaderPackage.mfx. Defaults to {DEFAULT_MFX}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help=(
            "Output .obj path or output directory. When a directory is passed, "
            "<mod stem>.obj is written inside it."
        ),
    )
    parser.add_argument("--manifest", type=Path, help="Write JSON manifest")
    parser.add_argument("--texture", type=Path, help="Optional PNG for a simple MTL")
    parser.add_argument(
        "--position-mode",
        choices=("bind-pose", "observed-bounds", "raw-snorm16"),
        default="bind-pose",
    )
    parser.add_argument(
        "--axis-mode",
        choices=("engine", "blender"),
        default="engine",
        help=(
            "Coordinate basis for OBJ output. engine keeps native MOD coordinates "
            "(rotate=0). blender applies the legacy Blender axis remap."
        ),
    )
    parser.add_argument(
        "--lod",
        type=int,
        choices=(0, 1, 2),
        default=0,
        help=(
            "LOD level for equip-style MOD files. 0 is highest detail. "
            "When a material has no LOD chain, all of its primitives are exported."
        ),
    )
    args = parser.parse_args()
    obj_path = resolve_obj_output_path(args.mod, args.output)

    manifest = write_obj_probe(
        args.mod,
        args.mfx,
        obj_path,
        args.manifest,
        args.position_mode,
        args.axis_mode,
        args.texture,
        args.lod,
    )
    print(
        "wrote {obj} ({vertices} vertices, {faces} faces, lod={lod}, mode={mode})".format(
            obj=obj_path,
            vertices=manifest["vertices"],
            faces=manifest["faces"],
            lod=manifest["lod"],
            mode=args.position_mode,
        )
    )
    if manifest["out_of_range_faces"]:
        print(f"skipped {manifest['out_of_range_faces']} out-of-range faces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
