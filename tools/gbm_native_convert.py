#!/usr/bin/env python3
"""Pure-Python in-memory MOD -> OBJ/FBX/GLB conversion."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from gbm_fbx_writer import validate_fbx_bytes, write_fbx_bytes
from gbm_gltf_writer import parse_glb, validate_glb_bytes, write_glb_bytes
from gbm_model_mesh import MeshData, decode_mesh, mesh_counts
from gbm_obj_writer import parse_obj_counts, write_obj_bytes


FORMAT_ALIASES = {"gltf": "glb", "glb": "glb", "obj": "obj", "fbx": "fbx"}


@dataclass(frozen=True)
class NativeConvertResult:
    mod: Path
    output_root: Path
    formats: tuple[str, ...]
    obj: Path | None
    mtl: Path | None
    glb: Path | None
    fbx: Path | None
    counts: dict[str, int]
    checks: dict[str, dict[str, int]]


def parse_formats(value: str) -> tuple[str, ...]:
    formats = []
    for raw in value.split(","):
        item = raw.strip().lower()
        if not item:
            continue
        if item == "all":
            for normalized in ("obj", "fbx", "glb"):
                if normalized not in formats:
                    formats.append(normalized)
            continue
        if item == "both":
            for normalized in ("obj", "fbx"):
                if normalized not in formats:
                    formats.append(normalized)
            continue
        if item not in FORMAT_ALIASES:
            raise ValueError(f"unsupported native format: {item}")
        normalized = FORMAT_ALIASES[item]
        if normalized not in formats:
            formats.append(normalized)
    if not formats:
        raise ValueError("at least one format is required")
    return tuple(formats)


def _check_obj(mesh: MeshData, obj_bytes: bytes) -> dict[str, int]:
    counts = parse_obj_counts(obj_bytes)
    expected = mesh_counts(mesh)
    if counts["vertices"] != expected["vertices"] or counts["triangles"] != expected["triangles"]:
        raise ValueError(f"OBJ count mismatch: {counts} != {expected}")
    return counts


def _check_glb(mesh: MeshData, glb_bytes: bytes) -> dict[str, int]:
    validate_glb_bytes(glb_bytes)
    gltf, _ = parse_glb(glb_bytes)
    vertex_count = 0
    triangle_index_count = 0
    for mesh_def in gltf.get("meshes", []):
        for primitive in mesh_def.get("primitives", []):
            vertex_count += gltf["accessors"][primitive["attributes"]["POSITION"]]["count"]
            triangle_index_count += gltf["accessors"][primitive["indices"]]["count"]
    expected = mesh_counts(mesh)
    triangles = triangle_index_count // 3
    if vertex_count != expected["vertices"] or triangles != expected["triangles"]:
        raise ValueError(
            f"GLB count mismatch: vertices={vertex_count} triangles={triangles} expected={expected}"
        )
    return {"vertices": vertex_count, "triangles": triangles, "meshes": len(gltf.get("meshes", []))}


def _check_fbx(mesh: MeshData, fbx_bytes: bytes) -> dict[str, int]:
    counts = validate_fbx_bytes(fbx_bytes)
    expected = mesh_counts(mesh)
    if counts["geometry_vertices"] != expected["vertices"]:
        raise ValueError(f"FBX vertex mismatch: {counts} != {expected}")
    return counts


def convert_mod_native(
    mod_path: Path,
    output_root: Path,
    *,
    mfx_path: Path,
    mrl_path: Path | None,
    png_dir: Path | None,
    formats: Sequence[str] = ("obj", "fbx", "glb"),
    lod: int = 0,
) -> NativeConvertResult:
    normalized_formats = tuple(FORMAT_ALIASES.get(item, item) for item in formats)
    mesh = decode_mesh(
        mod_path,
        mfx_path,
        mrl_path=mrl_path,
        png_dir=png_dir,
        lod=lod,
        bake_space=True,
    )
    counts = mesh_counts(mesh)
    stem = mod_path.stem
    pending: list[tuple[Path, bytes]] = []
    checks: dict[str, dict[str, int]] = {}
    obj_path = mtl_path = glb_path = fbx_path = None

    if "obj" in normalized_formats:
        obj_path = output_root / "obj" / f"{stem}.obj"
        mtl_path = output_root / "obj" / f"{stem}.mtl"
        obj_bytes, mtl_bytes = write_obj_bytes(
            mesh, mtl_name=mtl_path.name, mtl_dir=mtl_path.parent
        )
        checks["obj"] = _check_obj(mesh, obj_bytes)
        pending.extend([(obj_path, obj_bytes), (mtl_path, mtl_bytes)])

    if "glb" in normalized_formats:
        glb_path = output_root / "gltf" / f"{stem}.glb"
        glb_bytes = write_glb_bytes(mesh)
        checks["glb"] = _check_glb(mesh, glb_bytes)
        pending.append((glb_path, glb_bytes))

    if "fbx" in normalized_formats:
        fbx_path = output_root / "fbx" / f"{stem}.fbx"
        fbx_bytes = write_fbx_bytes(mesh)
        checks["fbx"] = _check_fbx(mesh, fbx_bytes)
        pending.append((fbx_path, fbx_bytes))

    for path, data in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    return NativeConvertResult(
        mod=mod_path,
        output_root=output_root,
        formats=normalized_formats,
        obj=obj_path,
        mtl=mtl_path,
        glb=glb_path,
        fbx=fbx_path,
        counts=counts,
        checks=checks,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert one GBM MOD using native writers.")
    parser.add_argument("mod", type=Path, help="Input .mod file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output root")
    parser.add_argument("--mfx", type=Path, required=True, help="ShaderPackage.mfx")
    parser.add_argument("--mrl", type=Path, help="Matching .mrl file")
    parser.add_argument("--png-dir", type=Path, help="Directory containing converted PNG files")
    parser.add_argument(
        "--format",
        default="obj,fbx,gltf",
        help="Comma-separated obj,fbx,gltf list. Defaults to all native formats.",
    )
    parser.add_argument("--lod", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--report", type=Path, help="Write JSON conversion report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = convert_mod_native(
        args.mod.resolve(),
        args.output.resolve(),
        mfx_path=args.mfx.resolve(),
        mrl_path=args.mrl.resolve() if args.mrl else None,
        png_dir=args.png_dir.resolve() if args.png_dir else None,
        formats=parse_formats(args.format),
        lod=args.lod,
    )
    payload = asdict(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
