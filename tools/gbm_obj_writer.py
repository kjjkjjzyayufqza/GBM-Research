#!/usr/bin/env python3
"""In-memory OBJ/MTL writer for MeshData."""

from __future__ import annotations

import os
from pathlib import Path

from gbm_model_mesh import MeshData


def _fmt(value: float) -> str:
    return f"{float(value):.6f}"


def _rel(path: Path, mtl_dir: Path | None) -> str:
    if mtl_dir is None:
        return path.as_posix()
    return os.path.relpath(path, mtl_dir).replace("\\", "/")


def write_mtl_bytes(mesh: MeshData, mtl_dir: Path | None = None) -> bytes:
    lines: list[str] = []
    for material in mesh.materials:
        lines.extend(
            [
                f"newmtl {material.name}",
                "Ka 0.000000 0.000000 0.000000",
                "Kd 1.000000 1.000000 1.000000",
                "Ks 0.000000 0.000000 0.000000",
                "d 1.000000",
                "illum 1",
            ]
        )
        if material.base_png is not None:
            lines.append(f"map_Kd {_rel(material.base_png, mtl_dir)}")
        if material.normal_png is not None:
            lines.append(f"map_Bump {_rel(material.normal_png, mtl_dir)}")
        lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def write_obj_bytes(
    mesh: MeshData,
    *,
    mtl_name: str | None = None,
    mtl_dir: Path | None = None,
) -> tuple[bytes, bytes]:
    lines: list[str] = [
        "# GBM native OBJ export",
        f"# mesh: {mesh.name}",
        f"# space: {mesh.space}",
    ]
    if mtl_name:
        lines.append(f"mtllib {mtl_name}")

    vertex_base = 1
    for part in mesh.parts:
        material_name = next(
            (
                material.name
                for material in mesh.materials
                if material.index == part.material_index
            ),
            f"mat_{part.material_index}",
        )
        lines.append("")
        lines.append(f"o {part.name}")
        lines.append(f"usemtl {material_name}")
        for position in part.positions:
            lines.append(f"v {_fmt(position[0])} {_fmt(position[1])} {_fmt(position[2])}")
        for uv in part.uvs:
            lines.append(f"vt {_fmt(uv[0])} {_fmt(uv[1])}")
        for normal in part.normals:
            lines.append(f"vn {_fmt(normal[0])} {_fmt(normal[1])} {_fmt(normal[2])}")
        for face in part.triangles:
            a, b, c = (vertex_base + int(index) for index in face)
            lines.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")
        vertex_base += len(part.positions)
    lines.append("")
    return ("\n".join(lines)).encode("utf-8"), write_mtl_bytes(mesh, mtl_dir)


def parse_obj_counts(obj_bytes: bytes) -> dict[str, int]:
    lines = obj_bytes.decode("utf-8").splitlines()
    materials = {
        line.split(maxsplit=1)[1]
        for line in lines
        if line.startswith("usemtl ") and len(line.split(maxsplit=1)) == 2
    }
    return {
        "vertices": sum(1 for line in lines if line.startswith("v ")),
        "uvs": sum(1 for line in lines if line.startswith("vt ")),
        "normals": sum(1 for line in lines if line.startswith("vn ")),
        "triangles": sum(1 for line in lines if line.startswith("f ")),
        "objects": sum(1 for line in lines if line.startswith("o ")),
        "materials": len(materials),
    }

