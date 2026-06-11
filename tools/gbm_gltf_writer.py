#!/usr/bin/env python3
"""In-memory binary glTF (GLB 2.0) writer for MeshData."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from gbm_model_mesh import MeshData


GLB_MAGIC = 0x46546C67
GLB_VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
UNSIGNED_INT = 5125
UNSIGNED_SHORT = 5123


def _align4(data: bytes, pad: bytes = b"\x00") -> bytes:
    extra = (-len(data)) % 4
    return data + pad * extra


def _uri(path: Path) -> str:
    return path.as_posix()


class _GlbBuilder:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.buffer_views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def add_view(self, data: bytes, *, target: int | None = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        offset = len(self.bin)
        self.bin.extend(data)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.buffer_views.append(view)
        return len(self.buffer_views) - 1

    def add_accessor(
        self,
        array: np.ndarray,
        *,
        component_type: int,
        accessor_type: str,
        target: int | None = None,
        include_min_max: bool = False,
    ) -> int:
        contiguous = np.ascontiguousarray(array)
        view = self.add_view(contiguous.tobytes(), target=target)
        accessor: dict[str, Any] = {
            "bufferView": view,
            "byteOffset": 0,
            "componentType": component_type,
            "count": int(len(contiguous)),
            "type": accessor_type,
        }
        if include_min_max and len(contiguous):
            accessor["min"] = contiguous.min(axis=0).astype(float).tolist()
            accessor["max"] = contiguous.max(axis=0).astype(float).tolist()
        self.accessors.append(accessor)
        return len(self.accessors) - 1


def write_glb_bytes(mesh: MeshData) -> bytes:
    builder = _GlbBuilder()
    images: list[dict[str, Any]] = []
    textures: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    image_index_by_path: dict[str, int] = {}

    def image_for(path: Path) -> int:
        key = path.as_posix()
        if key not in image_index_by_path:
            image_index_by_path[key] = len(images)
            images.append({"uri": _uri(path)})
        return image_index_by_path[key]

    for material in mesh.materials:
        gltf_material: dict[str, Any] = {"name": material.name, "pbrMetallicRoughness": {}}
        if material.base_png is not None:
            texture_index = len(textures)
            textures.append({"source": image_for(material.base_png)})
            gltf_material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": texture_index}
        if material.normal_png is not None:
            texture_index = len(textures)
            textures.append({"source": image_for(material.normal_png)})
            gltf_material["normalTexture"] = {"index": texture_index}
        materials.append(gltf_material)

    bone_nodes: list[dict[str, Any]] = []
    for bone in mesh.bones:
        node: dict[str, Any] = {
            "name": bone.name,
            "matrix": bone.world_matrix.astype(float).T.reshape(-1).tolist(),
        }
        bone_nodes.append(node)
    for index, bone in enumerate(mesh.bones):
        if bone.parent >= 0:
            bone_nodes[bone.parent].setdefault("children", []).append(index)

    inverse_bind_accessor = None
    skins: list[dict[str, Any]] = []
    if mesh.bones:
        inverse_binds = np.stack(
            [np.linalg.inv(bone.world_matrix).T.reshape(16) for bone in mesh.bones]
        ).astype(np.float32)
        inverse_bind_accessor = builder.add_accessor(
            inverse_binds,
            component_type=FLOAT,
            accessor_type="MAT4",
        )
        skins.append(
            {
                "name": f"{mesh.name}_skin",
                "joints": list(range(len(mesh.bones))),
                "inverseBindMatrices": inverse_bind_accessor,
            }
        )

    mesh_defs: list[dict[str, Any]] = []
    mesh_nodes: list[dict[str, Any]] = []
    material_to_index = {material.index: index for index, material in enumerate(mesh.materials)}
    for part in mesh.parts:
        attributes: dict[str, int] = {
            "POSITION": builder.add_accessor(
                part.positions.astype(np.float32),
                component_type=FLOAT,
                accessor_type="VEC3",
                target=ARRAY_BUFFER,
                include_min_max=True,
            ),
            "NORMAL": builder.add_accessor(
                part.normals.astype(np.float32),
                component_type=FLOAT,
                accessor_type="VEC3",
                target=ARRAY_BUFFER,
            ),
            "TEXCOORD_0": builder.add_accessor(
                part.uvs.astype(np.float32),
                component_type=FLOAT,
                accessor_type="VEC2",
                target=ARRAY_BUFFER,
            ),
        }
        if part.joints is not None and part.weights is not None:
            attributes["JOINTS_0"] = builder.add_accessor(
                part.joints.astype(np.uint16),
                component_type=UNSIGNED_SHORT,
                accessor_type="VEC4",
                target=ARRAY_BUFFER,
            )
            attributes["WEIGHTS_0"] = builder.add_accessor(
                part.weights.astype(np.float32),
                component_type=FLOAT,
                accessor_type="VEC4",
                target=ARRAY_BUFFER,
            )
        indices = builder.add_accessor(
            part.triangles.reshape(-1).astype(np.uint32),
            component_type=UNSIGNED_INT,
            accessor_type="SCALAR",
            target=ELEMENT_ARRAY_BUFFER,
        )
        mesh_index = len(mesh_defs)
        mesh_defs.append(
            {
                "name": part.name,
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices,
                        "material": material_to_index.get(part.material_index, 0),
                    }
                ],
            }
        )
        node: dict[str, Any] = {"name": part.name, "mesh": mesh_index}
        if skins:
            node["skin"] = 0
        mesh_nodes.append(node)

    nodes = bone_nodes + mesh_nodes
    scene_nodes = [index for index, bone in enumerate(mesh.bones) if bone.parent < 0]
    scene_nodes.extend(range(len(bone_nodes), len(nodes)))
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "GBM-Research native exporter"},
        "scene": 0,
        "scenes": [{"nodes": scene_nodes}],
        "nodes": nodes,
        "meshes": mesh_defs,
        "materials": materials,
        "buffers": [{"byteLength": len(_align4(bytes(builder.bin)))}],
        "bufferViews": builder.buffer_views,
        "accessors": builder.accessors,
    }
    if images:
        gltf["images"] = images
        gltf["textures"] = textures
    if skins:
        gltf["skins"] = skins

    json_bytes = _align4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    bin_bytes = _align4(bytes(builder.bin))
    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    return b"".join(
        [
            struct.pack("<III", GLB_MAGIC, GLB_VERSION, total_length),
            struct.pack("<II", len(json_bytes), JSON_CHUNK),
            json_bytes,
            struct.pack("<II", len(bin_bytes), BIN_CHUNK),
            bin_bytes,
        ]
    )


def parse_glb(glb_bytes: bytes) -> tuple[dict[str, Any], bytes]:
    magic, version, length = struct.unpack_from("<III", glb_bytes, 0)
    if magic != GLB_MAGIC or version != GLB_VERSION or length != len(glb_bytes):
        raise ValueError("invalid GLB header")
    offset = 12
    json_doc: dict[str, Any] | None = None
    bin_chunk = b""
    while offset < len(glb_bytes):
        chunk_length, chunk_type = struct.unpack_from("<II", glb_bytes, offset)
        offset += 8
        chunk = glb_bytes[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == JSON_CHUNK:
            json_doc = json.loads(chunk.rstrip(b" ").decode("utf-8"))
        elif chunk_type == BIN_CHUNK:
            bin_chunk = chunk
    if json_doc is None:
        raise ValueError("GLB has no JSON chunk")
    return json_doc, bin_chunk


def validate_glb_bytes(glb_bytes: bytes) -> dict[str, int]:
    gltf, bin_chunk = parse_glb(glb_bytes)
    for view in gltf.get("bufferViews", []):
        start = int(view.get("byteOffset", 0))
        end = start + int(view["byteLength"])
        if end > len(bin_chunk):
            raise ValueError(f"bufferView out of range: {view}")
    return {
        "meshes": len(gltf.get("meshes", [])),
        "skins": len(gltf.get("skins", [])),
        "nodes": len(gltf.get("nodes", [])),
        "accessors": len(gltf.get("accessors", [])),
    }

