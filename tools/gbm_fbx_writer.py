#!/usr/bin/env python3
"""Minimal binary FBX 7400 writer and structural parser for MeshData."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gbm_model_mesh import MeshData


FBX_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
FBX_VERSION = 7400
NULL_RECORD = b"\x00" * 13


@dataclass
class FbxNode:
    name: str
    props: list[Any] = field(default_factory=list)
    children: list["FbxNode"] = field(default_factory=list)


def _prop(value: Any) -> bytes:
    if isinstance(value, bool):
        return b"C" + struct.pack("<?", value)
    if isinstance(value, int):
        if -(2**31) <= value < 2**31:
            return b"I" + struct.pack("<i", value)
        return b"L" + struct.pack("<q", value)
    if isinstance(value, float):
        return b"D" + struct.pack("<d", value)
    if isinstance(value, str):
        data = value.encode("utf-8")
        return b"S" + struct.pack("<I", len(data)) + data
    if isinstance(value, bytes):
        return b"R" + struct.pack("<I", len(value)) + value
    if isinstance(value, np.ndarray):
        return _array_prop(value)
    raise TypeError(f"unsupported FBX property type: {type(value).__name__}")


def _array_prop(array: np.ndarray) -> bytes:
    if array.dtype.kind in ("f",):
        code = b"d"
        payload = np.ascontiguousarray(array.astype("<f8")).tobytes()
    elif array.dtype.itemsize <= 4:
        code = b"i"
        payload = np.ascontiguousarray(array.astype("<i4")).tobytes()
    else:
        code = b"l"
        payload = np.ascontiguousarray(array.astype("<i8")).tobytes()
    compressed = zlib.compress(payload)
    return code + struct.pack("<III", int(array.size), 1, len(compressed)) + compressed


def _node_bytes(node: FbxNode, start_offset: int) -> bytes:
    prop_bytes = b"".join(_prop(prop) for prop in node.props)
    name_bytes = node.name.encode("utf-8")
    header_length = 13 + len(name_bytes)
    child_offset = start_offset + header_length + len(prop_bytes)
    children = bytearray()
    for child in node.children:
        blob = _node_bytes(child, child_offset + len(children))
        children.extend(blob)
    end_offset = start_offset + header_length + len(prop_bytes) + len(children) + len(NULL_RECORD)
    return b"".join(
        [
            struct.pack("<III", end_offset, len(node.props), len(prop_bytes)),
            struct.pack("<B", len(name_bytes)),
            name_bytes,
            prop_bytes,
            bytes(children),
            NULL_RECORD,
        ]
    )


def _flatten_mesh(mesh: MeshData) -> tuple[np.ndarray, np.ndarray]:
    positions = []
    triangles = []
    offset = 0
    for part in mesh.parts:
        positions.append(part.positions.astype(np.float64))
        triangles.append(part.triangles.astype(np.int64) + offset)
        offset += len(part.positions)
    all_positions = (
        np.concatenate(positions).astype(np.float64)
        if positions
        else np.zeros((0, 3), dtype=np.float64)
    )
    all_triangles = (
        np.concatenate(triangles).astype(np.int64)
        if triangles
        else np.zeros((0, 3), dtype=np.int64)
    )
    polygon_indices = []
    for tri in all_triangles:
        polygon_indices.extend([int(tri[0]), int(tri[1]), -int(tri[2]) - 1])
    return all_positions.reshape(-1), np.array(polygon_indices, dtype=np.int32)


def _objects(mesh: MeshData) -> FbxNode:
    vertices, polygon_indices = _flatten_mesh(mesh)
    children: list[FbxNode] = [
        FbxNode(
            "Geometry",
            [1000, f"Geometry::{mesh.name}", "Mesh"],
            [
                FbxNode("Vertices", [vertices]),
                FbxNode("PolygonVertexIndex", [polygon_indices]),
                FbxNode("GeometryVersion", [124]),
            ],
        )
    ]
    for index, part in enumerate(mesh.parts):
        children.append(FbxNode("Model", [2000 + index, f"Model::{part.name}", "Mesh"]))
    for index, material in enumerate(mesh.materials):
        children.append(
            FbxNode("Material", [3000 + index, f"Material::{material.name}", ""])
        )
    for index, bone in enumerate(mesh.bones):
        children.append(
            FbxNode("NodeAttribute", [4000 + index, f"NodeAttribute::{bone.name}", "LimbNode"])
        )
        children.append(
            FbxNode("Model", [5000 + index, f"Model::{bone.name}", "LimbNode"])
        )
    if mesh.bones:
        children.append(FbxNode("Deformer", [6000, f"Deformer::{mesh.name}_skin", "Skin"]))
        used_bones = _used_bones(mesh)
        for bone_index in used_bones:
            weights = _bone_weights(mesh, bone_index)
            children.append(
                FbxNode(
                    "Deformer",
                    [6100 + bone_index, f"SubDeformer::cluster_{bone_index}", "Cluster"],
                    [
                        FbxNode("Indexes", [weights[0].astype(np.int32)]),
                        FbxNode("Weights", [weights[1].astype(np.float64)]),
                        FbxNode(
                            "TransformLink",
                            [mesh.bones[bone_index].world_matrix.astype(np.float64).T.reshape(-1)],
                        ),
                    ],
                )
            )
        children.append(FbxNode("Pose", [7000, f"Pose::{mesh.name}_bind", "BindPose"]))
    return FbxNode("Objects", children=children)


def _used_bones(mesh: MeshData) -> list[int]:
    used: set[int] = set()
    for part in mesh.parts:
        if part.joints is None or part.weights is None:
            continue
        mask = part.weights > 0.0
        used.update(int(value) for value in part.joints[mask])
    return sorted(index for index in used if 0 <= index < len(mesh.bones))


def _bone_weights(mesh: MeshData, bone_index: int) -> tuple[np.ndarray, np.ndarray]:
    indexes = []
    weights = []
    vertex_offset = 0
    for part in mesh.parts:
        if part.joints is not None and part.weights is not None:
            for vertex_index in range(len(part.positions)):
                for slot in range(4):
                    if int(part.joints[vertex_index, slot]) == bone_index and part.weights[vertex_index, slot] > 0:
                        indexes.append(vertex_offset + vertex_index)
                        weights.append(float(part.weights[vertex_index, slot]))
        vertex_offset += len(part.positions)
    return np.array(indexes, dtype=np.int32), np.array(weights, dtype=np.float64)


def _connections(mesh: MeshData) -> FbxNode:
    children = []
    for index, _part in enumerate(mesh.parts):
        children.append(FbxNode("C", ["OO", 2000 + index, 1000]))
    for index, _material in enumerate(mesh.materials):
        children.append(FbxNode("C", ["OO", 3000 + index, 1000]))
    for index, bone in enumerate(mesh.bones):
        children.append(FbxNode("C", ["OO", 4000 + index, 5000 + index]))
        if bone.parent >= 0:
            children.append(FbxNode("C", ["OO", 5000 + index, 5000 + bone.parent]))
    if mesh.bones:
        children.append(FbxNode("C", ["OO", 6000, 1000]))
        for bone_index in _used_bones(mesh):
            children.append(FbxNode("C", ["OO", 6100 + bone_index, 6000]))
            children.append(FbxNode("C", ["OO", 6100 + bone_index, 5000 + bone_index]))
    return FbxNode("Connections", children=children)


def write_fbx_bytes(mesh: MeshData) -> bytes:
    roots = [
        FbxNode(
            "FBXHeaderExtension",
            children=[
                FbxNode("FBXHeaderVersion", [1003]),
                FbxNode("FBXVersion", [FBX_VERSION]),
                FbxNode("Creator", ["GBM-Research native exporter"]),
            ],
        ),
        FbxNode(
            "GlobalSettings",
            children=[
                FbxNode("Version", [1000]),
                FbxNode("Properties70", children=[FbxNode("P", ["UnitScaleFactor", "double", "Number", "", 1.0])]),
            ],
        ),
        FbxNode("Definitions", children=[FbxNode("Version", [100])]),
        _objects(mesh),
        _connections(mesh),
    ]
    out = bytearray(FBX_MAGIC)
    out.extend(struct.pack("<I", FBX_VERSION))
    for root in roots:
        out.extend(_node_bytes(root, len(out)))
    out.extend(NULL_RECORD)
    return bytes(out)


def _parse_prop(data: bytes, offset: int) -> tuple[Any, int]:
    code = data[offset : offset + 1]
    offset += 1
    if code == b"C":
        return struct.unpack_from("<?", data, offset)[0], offset + 1
    if code == b"I":
        return struct.unpack_from("<i", data, offset)[0], offset + 4
    if code == b"L":
        return struct.unpack_from("<q", data, offset)[0], offset + 8
    if code == b"D":
        return struct.unpack_from("<d", data, offset)[0], offset + 8
    if code in (b"S", b"R"):
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        value = data[offset : offset + length]
        if code == b"S":
            value = value.decode("utf-8")
        return value, offset + length
    if code in (b"d", b"i", b"l"):
        count, encoding, byte_length = struct.unpack_from("<III", data, offset)
        offset += 12
        payload = data[offset : offset + byte_length]
        offset += byte_length
        if encoding == 1:
            payload = zlib.decompress(payload)
        dtype = {"d": "<f8", "i": "<i4", "l": "<i8"}[code.decode("ascii")]
        return np.frombuffer(payload, dtype=np.dtype(dtype), count=count), offset
    raise ValueError(f"unsupported FBX property code: {code!r}")


def parse_fbx_nodes(fbx_bytes: bytes) -> list[FbxNode]:
    if not fbx_bytes.startswith(FBX_MAGIC):
        raise ValueError("invalid FBX magic")
    version = struct.unpack_from("<I", fbx_bytes, len(FBX_MAGIC))[0]
    if version != FBX_VERSION:
        raise ValueError(f"unsupported FBX version: {version}")
    nodes, _offset = _parse_nodes(fbx_bytes, len(FBX_MAGIC) + 4, len(fbx_bytes))
    return nodes


def _parse_nodes(data: bytes, offset: int, limit: int) -> tuple[list[FbxNode], int]:
    nodes: list[FbxNode] = []
    while offset + 13 <= limit:
        end_offset, prop_count, prop_len = struct.unpack_from("<III", data, offset)
        name_len = data[offset + 12]
        if end_offset == 0 and prop_count == 0 and prop_len == 0 and name_len == 0:
            return nodes, offset + 13
        name_start = offset + 13
        name = data[name_start : name_start + name_len].decode("utf-8")
        prop_offset = name_start + name_len
        props = []
        child_offset = prop_offset + prop_len
        while prop_offset < child_offset:
            prop, prop_offset = _parse_prop(data, prop_offset)
            props.append(prop)
        children, _ = _parse_nodes(data, child_offset, end_offset - 13)
        nodes.append(FbxNode(name, props, children))
        offset = end_offset
    return nodes, offset


def _walk(nodes: list[FbxNode]) -> list[FbxNode]:
    out = []
    for node in nodes:
        out.append(node)
        out.extend(_walk(node.children))
    return out


def validate_fbx_bytes(fbx_bytes: bytes) -> dict[str, int]:
    nodes = parse_fbx_nodes(fbx_bytes)
    all_nodes = _walk(nodes)
    geometry_vertices = 0
    for node in all_nodes:
        if node.name == "Vertices" and node.props and isinstance(node.props[0], np.ndarray):
            geometry_vertices += int(len(node.props[0]) // 3)
    return {
        "geometry_vertices": geometry_vertices,
        "geometry_count": sum(1 for node in all_nodes if node.name == "Geometry"),
        "skin_count": sum(
            1
            for node in all_nodes
            if node.name == "Deformer" and len(node.props) >= 3 and node.props[2] == "Skin"
        ),
        "cluster_count": sum(
            1
            for node in all_nodes
            if node.name == "Deformer" and len(node.props) >= 3 and node.props[2] == "Cluster"
        ),
        "pose_count": sum(1 for node in all_nodes if node.name == "Pose"),
        "limb_node_count": sum(
            1
            for node in all_nodes
            if node.name == "Model" and len(node.props) >= 3 and node.props[2] == "LimbNode"
        ),
    }

