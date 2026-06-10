#!/usr/bin/env python3
"""Diagnostic: verify bone bind positions match skinned vertex centroids.

For each bone, compare the bone's bind-pose world translation against the
weighted centroid of all vertices it influences, in raw engine space.
A consistent rig keeps these close; a mirrored rig flips the X sign.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from gbm_mfx_inspect import parse_input_layouts
from gbm_mod_inspect import parse_header, parse_primitive_records
from gbm_mod_obj_probe import (
    decode_element,
    derive_bind_decode_matrix,
    find_element,
    matrix_from_bytes,
    multiply_matrix,
    parse_bone_palettes,
    position3,
    select_primitives_for_lod,
    transform_row_vector,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mod", type=Path)
    parser.add_argument("--mfx", type=Path, default=TOOLS_DIR / "ShaderPackage.mfx")
    parser.add_argument("--lod", type=int, default=0)
    args = parser.parse_args()

    data = args.mod.read_bytes()
    header = parse_header(args.mod, data)
    records = select_primitives_for_lod(parse_primitive_records(data, header), args.lod)
    _, layouts = parse_input_layouts(args.mfx)
    palettes = parse_bone_palettes(data, header)
    bind_decode_matrix, delta, parents = derive_bind_decode_matrix(data, header)

    bone_info_offset = header.bone_section_offset
    local_matrix_offset = bone_info_offset + header.bone_count * 24
    local_matrices = [
        matrix_from_bytes(data, local_matrix_offset + bone_index * 64)
        for bone_index in range(header.bone_count)
    ]
    world_matrices = []
    for bone_index, local_matrix in enumerate(local_matrices):
        parent = parents[bone_index]
        world_matrices.append(
            local_matrix
            if parent == 0xFF
            else multiply_matrix(local_matrix, world_matrices[parent])
        )

    accum = {i: [0.0, 0.0, 0.0, 0.0] for i in range(header.bone_count)}

    for record in records:
        layout = layouts[record.resource_hash_or_key & 0xFFF]
        position_element = find_element(layout, "Position")
        joint_element = find_element(layout, "Joint")
        try:
            weight_element = find_element(layout, "Weight")
        except ValueError:
            weight_element = None
        palette = palettes[record.field_24]
        vertex_start = (
            header.vertex_buffer_offset
            + record.vertex_base_offset
            + record.vertex_start * record.vertex_size
        )
        for vertex_index in range(record.vertex_count):
            raw = data[
                vertex_start
                + vertex_index * record.vertex_size : vertex_start
                + (vertex_index + 1) * record.vertex_size
            ]
            raw_position = position3(decode_element(raw, position_element))
            world = transform_row_vector((*raw_position, 1.0), bind_decode_matrix)
            joints = list(
                raw[
                    joint_element.byte_offset : joint_element.byte_offset
                    + joint_element.component_count
                ]
            )
            joints.extend([0] * (4 - len(joints)))
            if weight_element is None:
                weights = [255, 0, 0, 0]
            else:
                explicit = list(
                    raw[
                        weight_element.byte_offset : weight_element.byte_offset
                        + weight_element.component_count
                    ]
                )
                weights = explicit + [255 - sum(explicit)]
                weights.extend([0] * (4 - len(weights)))
            for component, raw_weight in enumerate(weights[:4]):
                if raw_weight == 0:
                    continue
                local_joint = joints[component]
                if local_joint >= len(palette):
                    continue
                bone = palette[local_joint]
                weight = raw_weight / 255.0
                entry = accum[bone]
                entry[0] += world[0] * weight
                entry[1] += world[1] * weight
                entry[2] += world[2] * weight
                entry[3] += weight

    print(f"bone_count={header.bone_count} bind_delta={delta:.6f}")
    print(
        f"{'bone':>4} {'bone_x':>10} {'bone_y':>10} {'bone_z':>10} "
        f"{'cent_x':>10} {'cent_y':>10} {'cent_z':>10} {'dist':>8} {'wsum':>8}"
    )
    sign_mismatch = 0
    checked = 0
    for bone_index in range(header.bone_count):
        entry = accum[bone_index]
        if entry[3] < 1.0:
            continue
        cx, cy, cz = (entry[0] / entry[3], entry[1] / entry[3], entry[2] / entry[3])
        # Row-vector convention: translation is row 3 of the world matrix.
        bx, by, bz = world_matrices[bone_index][3][:3]
        dist = math.sqrt((cx - bx) ** 2 + (cy - by) ** 2 + (cz - bz) ** 2)
        flag = ""
        if abs(bx) > 3.0 and abs(cx) > 3.0 and (bx > 0) != (cx > 0):
            flag = "  <-- X SIGN MISMATCH"
            sign_mismatch += 1
        checked += 1
        print(
            f"{bone_index:>4} {bx:>10.3f} {by:>10.3f} {bz:>10.3f} "
            f"{cx:>10.3f} {cy:>10.3f} {cz:>10.3f} {dist:>8.2f} {entry[3]:>8.1f}{flag}"
        )
    print(f"\nchecked={checked} x_sign_mismatches={sign_mismatch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
