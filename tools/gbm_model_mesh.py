#!/usr/bin/env python3
"""Shared in-memory mesh contract and MOD decoder for native exports."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gbm_mfx_inspect import InputElement, InputLayout, parse_input_layouts
from gbm_mod_inspect import (
    ModHeader,
    PrimitiveRecord,
    parse_header,
    parse_primitive_records,
    read_material_names,
)
from gbm_mod_obj_probe import (
    collect_raw_position_bounds,
    decode_position,
    derive_bind_decode_matrix,
    find_element,
    iter_strip_faces,
    material_index,
    material_name,
    matrix_from_bytes,
    multiply_matrix,
    parse_bone_palettes,
    select_primitives_for_lod,
)
from gbm_mrl_inspect import material_bindings


@dataclass(frozen=True)
class MaterialDef:
    index: int
    name: str
    base_png: Path | None
    normal_png: Path | None


@dataclass(frozen=True)
class Bone:
    name: str
    parent: int
    world_matrix: np.ndarray


@dataclass(frozen=True)
class MeshPart:
    name: str
    material_index: int
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    triangles: np.ndarray
    joints: np.ndarray | None
    weights: np.ndarray | None


@dataclass(frozen=True)
class MeshData:
    name: str
    parts: tuple[MeshPart, ...]
    bones: tuple[Bone, ...]
    materials: tuple[MaterialDef, ...]
    space: str


AXIS_3 = np.array(
    [
        [-1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=np.float32,
)
AXIS_4 = np.identity(4, dtype=np.float32)
AXIS_4[:3, :3] = AXIS_3


def _element_dtype(element: InputElement) -> np.dtype:
    if element.format_id == 1:
        return np.dtype("<f4")
    if element.format_id in (2, 5):
        return np.dtype("<i2")
    if element.format_id == 8:
        return np.dtype("u1")
    if element.format_id == 9:
        return np.dtype("i1")
    if element.format_id == 10:
        return np.dtype("u1")
    raise ValueError(f"unsupported format {element.format_id} for {element.semantic}")


def vectorized_decode_element(
    vertex_bytes: bytes,
    vertex_count: int,
    stride: int,
    element: InputElement,
) -> np.ndarray:
    """Decode one vertex element for many vertices using numpy slicing."""

    byte_size = element.byte_size
    rows = np.frombuffer(vertex_bytes, dtype=np.uint8, count=vertex_count * stride)
    rows = rows.reshape(vertex_count, stride)
    raw = rows[:, element.byte_offset : element.byte_offset + byte_size].copy()
    values = raw.view(_element_dtype(element)).reshape(
        vertex_count, element.component_count
    )
    if element.format_id == 1:
        return values.astype(np.float32)
    if element.format_id == 2:
        return (values.astype(np.float32) / 1024.0).astype(np.float32)
    if element.format_id == 5:
        return np.maximum(-1.0, values.astype(np.float32) / 32767.0).astype(np.float32)
    if element.format_id == 8:
        return values.astype(np.float32)
    if element.format_id == 9:
        return np.maximum(-1.0, values.astype(np.float32) / 127.0).astype(np.float32)
    if element.format_id == 10:
        return (values.astype(np.float32) / 255.0).astype(np.float32)
    raise ValueError(f"unsupported format {element.format_id} for {element.semantic}")


def _optional_element(layout: InputLayout, semantic: str) -> InputElement | None:
    for element in layout.elements:
        if element.semantic == semantic:
            return element
    return None


def _normalize_vectors(values: np.ndarray, fallback: tuple[float, float, float]) -> np.ndarray:
    out = values.astype(np.float32, copy=True)
    lengths = np.linalg.norm(out, axis=1)
    bad = lengths <= 1.0e-8
    lengths[bad] = 1.0
    out = out / lengths[:, None]
    if np.any(bad):
        out[bad] = np.array(fallback, dtype=np.float32)
    return out


def _to_three(values: np.ndarray) -> np.ndarray:
    if values.shape[1] >= 3:
        return values[:, :3].astype(np.float32)
    if values.shape[1] == 2:
        return np.column_stack(
            [values[:, 0], values[:, 1], np.zeros(values.shape[0], dtype=np.float32)]
        ).astype(np.float32)
    raise ValueError(f"position has too few components: {values.shape[1]}")


def _decode_positions(
    raw_positions: np.ndarray,
    header: ModHeader,
    raw_mins: list[int],
    raw_maxs: list[int],
    bind_decode_matrix: tuple[tuple[float, float, float, float], ...],
) -> np.ndarray:
    matrix = np.array(bind_decode_matrix, dtype=np.float32)
    hom = np.column_stack(
        [raw_positions[:, :3], np.ones(raw_positions.shape[0], dtype=np.float32)]
    )
    decoded = hom @ matrix
    return decoded[:, :3].astype(np.float32)


def _decode_bones(data: bytes, header: ModHeader) -> tuple[Bone, ...]:
    if header.bone_count == 0:
        return ()
    bone_info_offset = header.bone_section_offset
    local_matrix_offset = bone_info_offset + header.bone_count * 24
    parents = [
        data[bone_info_offset + bone_index * 24 + 2]
        for bone_index in range(header.bone_count)
    ]
    local_matrices = [
        matrix_from_bytes(data, local_matrix_offset + bone_index * 64)
        for bone_index in range(header.bone_count)
    ]
    world_matrices = []
    for bone_index, local_matrix in enumerate(local_matrices):
        parent = parents[bone_index]
        if parent == 0xFF:
            world = local_matrix
        else:
            world = multiply_matrix(local_matrix, world_matrices[parent])
        world_matrices.append(world)
    bones = []
    for bone_index, world in enumerate(world_matrices):
        parent = -1 if parents[bone_index] == 0xFF else int(parents[bone_index])
        bones.append(
            Bone(
                name=f"bone_{bone_index:03d}",
                parent=parent,
                world_matrix=np.array(world, dtype=np.float32),
            )
        )
    return tuple(bones)


def _resolve_material_defs(
    data: bytes,
    header: ModHeader,
    used_indices: list[int],
    mrl_path: Path | None,
    png_dir: Path | None,
) -> tuple[MaterialDef, ...]:
    by_index: dict[int, MaterialDef] = {
        index: MaterialDef(index=index, name=material_name(index), base_png=None, normal_png=None)
        for index in used_indices
    }
    if mrl_path is not None and png_dir is not None:
        for binding in material_bindings(mrl_path, read_material_names(data, header)):
            if binding.index not in by_index:
                continue
            base_png = png_dir / f"{binding.base}.png" if binding.base else None
            normal_png = png_dir / f"{binding.normal}.png" if binding.normal else None
            by_index[binding.index] = MaterialDef(
                index=binding.index,
                name=material_name(binding.index),
                base_png=base_png,
                normal_png=normal_png,
            )
    return tuple(by_index[index] for index in used_indices)


def _palette_for_record(
    palettes: list[list[int]], record: PrimitiveRecord, bone_count: int
) -> list[int] | None:
    if not palettes or bone_count == 0:
        return None
    for candidate in (record.material_table_index, record.group_id, record.field_24):
        if 0 <= candidate < len(palettes):
            return palettes[candidate]
    return palettes[0]


def _decode_skin(
    vertex_block: bytes,
    record: PrimitiveRecord,
    layout: InputLayout,
    palettes: list[list[int]],
    bone_count: int,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    joint_element = _optional_element(layout, "Joint")
    if joint_element is None or bone_count == 0:
        return None, None
    local_joints = vectorized_decode_element(
        vertex_block, record.vertex_count, record.vertex_size, joint_element
    ).astype(np.int32)
    joints = np.zeros((record.vertex_count, 4), dtype=np.int32)
    columns = min(4, local_joints.shape[1])
    joints[:, :columns] = local_joints[:, :columns]
    palette = _palette_for_record(palettes, record, bone_count)
    if palette:
        mapped = np.zeros_like(joints)
        for local_index, bone_index in enumerate(palette):
            mapped[joints == local_index] = min(int(bone_index), bone_count - 1)
        joints = mapped
    else:
        joints = np.clip(joints, 0, max(0, bone_count - 1))

    weight_element = _optional_element(layout, "Weight")
    if weight_element is None:
        weights = np.zeros((record.vertex_count, 4), dtype=np.float32)
        weights[:, 0] = 1.0
        return joints, weights
    raw_weights = vectorized_decode_element(
        vertex_block, record.vertex_count, record.vertex_size, weight_element
    ).astype(np.float32)
    weights = np.zeros((record.vertex_count, 4), dtype=np.float32)
    columns = min(3, raw_weights.shape[1])
    weights[:, :columns] = raw_weights[:, :columns]
    weights[:, 3] = np.maximum(0.0, 1.0 - weights[:, :3].sum(axis=1))
    totals = weights.sum(axis=1)
    totals[totals <= 1.0e-8] = 1.0
    return joints, (weights / totals[:, None]).astype(np.float32)


def _record_vertex_block(data: bytes, header: ModHeader, record: PrimitiveRecord) -> bytes:
    start = header.vertex_buffer_offset + record.vertex_base_offset + (
        record.vertex_start * record.vertex_size
    )
    end = start + record.vertex_count * record.vertex_size
    return data[start:end]


def _decode_record_part(
    data: bytes,
    header: ModHeader,
    record: PrimitiveRecord,
    layout: InputLayout,
    raw_mins: list[int],
    raw_maxs: list[int],
    bind_decode_matrix: tuple[tuple[float, float, float, float], ...],
    palettes: list[list[int]],
    bone_count: int,
) -> MeshPart:
    vertex_block = _record_vertex_block(data, header, record)
    position_element = find_element(layout, "Position")
    normal_element = _optional_element(layout, "Normal")
    uv_element = _optional_element(layout, "TexCoord") or _optional_element(layout, "Texcoord")

    raw_positions = _to_three(
        vectorized_decode_element(
            vertex_block, record.vertex_count, record.vertex_size, position_element
        )
    )
    positions = _decode_positions(raw_positions, header, raw_mins, raw_maxs, bind_decode_matrix)

    if normal_element is None:
        normals = np.tile(
            np.array([[0.0, 1.0, 0.0]], dtype=np.float32), (record.vertex_count, 1)
        )
    else:
        normals = _normalize_vectors(
            _to_three(
                vectorized_decode_element(
                    vertex_block, record.vertex_count, record.vertex_size, normal_element
                )
            ),
            (0.0, 1.0, 0.0),
        )

    if uv_element is None:
        uvs = np.zeros((record.vertex_count, 2), dtype=np.float32)
    else:
        raw_uvs = vectorized_decode_element(
            vertex_block, record.vertex_count, record.vertex_size, uv_element
        )
        uvs = np.zeros((record.vertex_count, 2), dtype=np.float32)
        uvs[:, : min(2, raw_uvs.shape[1])] = raw_uvs[:, :2]
        uvs[:, 1] = 1.0 - uvs[:, 1]

    index_offset = header.index_buffer_offset + record.index_start * 2
    indices = list(struct.unpack_from(f"<{record.index_count}H", data, index_offset))
    faces = [
        face
        for face in iter_strip_faces(indices, record.vertex_start)
        if all(0 <= index < record.vertex_count for index in face)
    ]
    triangles = np.array(faces, dtype=np.int32).reshape((-1, 3))
    joints, weights = _decode_skin(vertex_block, record, layout, palettes, bone_count)
    mat_index = material_index(record)
    return MeshPart(
        name=f"part_{record.index:03d}_{material_name(mat_index)}",
        material_index=mat_index,
        positions=positions,
        normals=normals,
        uvs=uvs,
        triangles=triangles,
        joints=joints,
        weights=weights,
    )


def _merge_material_runs(name: str, parts: list[MeshPart]) -> tuple[MeshPart, ...]:
    merged: list[MeshPart] = []
    current: list[MeshPart] = []
    current_material: int | None = None
    run_index = 0
    for part in parts:
        if current and part.material_index != current_material:
            merged.append(_merge_parts(name, run_index, current))
            run_index += 1
            current = []
        current_material = part.material_index
        current.append(part)
    if current:
        merged.append(_merge_parts(name, run_index, current))
    return tuple(merged)


def _merge_parts(mesh_name: str, run_index: int, parts: list[MeshPart]) -> MeshPart:
    material = parts[0].material_index
    offsets = []
    total = 0
    for part in parts:
        offsets.append(total)
        total += len(part.positions)
    positions = np.concatenate([part.positions for part in parts]).astype(np.float32)
    normals = np.concatenate([part.normals for part in parts]).astype(np.float32)
    uvs = np.concatenate([part.uvs for part in parts]).astype(np.float32)
    triangles = np.concatenate(
        [
            part.triangles + offsets[index]
            for index, part in enumerate(parts)
            if len(part.triangles)
        ]
    ).astype(np.int32) if any(len(part.triangles) for part in parts) else np.zeros((0, 3), dtype=np.int32)

    has_skin = any(part.joints is not None and part.weights is not None for part in parts)
    joints = weights = None
    if has_skin:
        joint_arrays = []
        weight_arrays = []
        for part in parts:
            if part.joints is None or part.weights is None:
                joint_arrays.append(np.zeros((len(part.positions), 4), dtype=np.int32))
                weight = np.zeros((len(part.positions), 4), dtype=np.float32)
                weight[:, 0] = 1.0
                weight_arrays.append(weight)
            else:
                joint_arrays.append(part.joints)
                weight_arrays.append(part.weights)
        joints = np.concatenate(joint_arrays).astype(np.int32)
        weights = np.concatenate(weight_arrays).astype(np.float32)

    return MeshPart(
        name=f"{mesh_name}_mat_{material}" if run_index == 0 else f"{mesh_name}_mat_{material}_{run_index}",
        material_index=material,
        positions=positions,
        normals=normals,
        uvs=uvs,
        triangles=triangles,
        joints=joints,
        weights=weights,
    )


def decode_mesh(
    mod_path: Path,
    mfx_path: Path,
    *,
    mrl_path: Path | None = None,
    png_dir: Path | None = None,
    lod: int | None = 0,
    bake_space: bool = True,
) -> MeshData:
    data = mod_path.read_bytes()
    header = parse_header(mod_path, data)
    all_records = parse_primitive_records(data, header)
    records = all_records if lod is None else select_primitives_for_lod(all_records, lod)
    _, layouts = parse_input_layouts(mfx_path)
    bind_decode_matrix, _, _parents = derive_bind_decode_matrix(data, header)
    raw_mins, raw_maxs = collect_raw_position_bounds(data, header, records, layouts)
    palettes = parse_bone_palettes(data, header)
    bones = _decode_bones(data, header)
    decoded_parts: list[MeshPart] = []
    for record in records:
        layout = layouts[record.resource_hash_or_key & 0xFFF]
        if layout.stored_stride != record.vertex_size:
            raise ValueError(
                f"primitive {record.index} stride {record.vertex_size} does not match layout {layout.index}"
            )
        decoded_parts.append(
            _decode_record_part(
                data,
                header,
                record,
                layout,
                raw_mins,
                raw_maxs,
                bind_decode_matrix,
                palettes,
                len(bones),
            )
        )
    parts = _merge_material_runs(mod_path.stem, decoded_parts)
    used_materials = sorted({part.material_index for part in parts})
    mesh = MeshData(
        name=mod_path.stem,
        parts=parts,
        bones=bones,
        materials=_resolve_material_defs(data, header, used_materials, mrl_path, png_dir),
        space="engine",
    )
    return bake_blender_space(mesh) if bake_space else mesh


def bake_blender_space(mesh: MeshData) -> MeshData:
    if mesh.space == "blender":
        return mesh
    if mesh.space != "engine":
        raise ValueError(f"unsupported mesh space: {mesh.space}")

    baked_parts = []
    for part in mesh.parts:
        positions = (part.positions @ AXIS_3.T) * 0.01
        normals = _normalize_vectors(part.normals @ AXIS_3.T, (0.0, 1.0, 0.0))
        baked_parts.append(
            MeshPart(
                name=part.name,
                material_index=part.material_index,
                positions=positions.astype(np.float32),
                normals=normals.astype(np.float32),
                uvs=part.uvs.astype(np.float32),
                triangles=part.triangles.astype(np.int32),
                joints=part.joints.copy() if part.joints is not None else None,
                weights=part.weights.copy() if part.weights is not None else None,
            )
        )

    inv_axis = np.linalg.inv(AXIS_4)
    baked_bones = []
    for bone in mesh.bones:
        matrix = AXIS_4 @ bone.world_matrix.astype(np.float32) @ inv_axis
        matrix[:3, 3] *= 0.01
        baked_bones.append(
            Bone(name=bone.name, parent=bone.parent, world_matrix=matrix.astype(np.float32))
        )
    return MeshData(
        name=mesh.name,
        parts=tuple(baked_parts),
        bones=tuple(baked_bones),
        materials=mesh.materials,
        space="blender",
    )


def mesh_counts(mesh: MeshData) -> dict[str, int]:
    return {
        "parts": len(mesh.parts),
        "vertices": int(sum(len(part.positions) for part in mesh.parts)),
        "triangles": int(sum(len(part.triangles) for part in mesh.parts)),
        "bones": len(mesh.bones),
        "materials": len(mesh.materials),
    }
