#!/usr/bin/env python3
"""Core helpers for the GBM Blender add-on.

This module avoids importing bpy so normal unit tests can cover path handling,
lookup resolution, and texture-copy behavior. Blender-only scene operations live
in tools/gbm_blender_addon.py and tools/gbm_blender_convert.py.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TOOLS_DIR = Path(__file__).resolve().parent


def _is_blender_addon_install(tools_dir: Path) -> bool:
    parts = [part.casefold() for part in tools_dir.parts]
    try:
        scripts_idx = parts.index("scripts")
    except ValueError:
        return False
    return scripts_idx + 1 < len(parts) and parts[scripts_idx + 1] == "addons"


_IS_BUNDLED_ADDON = _is_blender_addon_install(TOOLS_DIR)
if _IS_BUNDLED_ADDON:
    PROJECT_DIR = TOOLS_DIR
    WORKSPACE_ROOT = Path.home()
    DEFAULT_WORK_ROOT = WORKSPACE_ROOT / "gbm_blender_addon_work"
    DEFAULT_OUTPUT_ROOT = WORKSPACE_ROOT / "gbm_blender_addon_exports"
else:
    PROJECT_DIR = TOOLS_DIR.parent
    WORKSPACE_ROOT = PROJECT_DIR.parent
    DEFAULT_WORK_ROOT = PROJECT_DIR / "out" / "blender_addon_work"
    DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "out" / "blender_addon_exports"
DEFAULT_ARCHIVE_ROOT = (
    WORKSPACE_ROOT / "com.bandainamcoent.gb_jp" / "files" / "dlc" / "archive"
)
DEFAULT_MFX = TOOLS_DIR / "ShaderPackage.mfx"


@dataclass(frozen=True)
class PreparedImport:
    arc_path: Path
    model_stem: str
    collection_name: str
    job: object


def require_directory(path_text: str, label: str) -> Path:
    if not str(path_text).strip():
        raise ValueError(f"{label} is required")
    path = Path(path_text).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return path.resolve()


def require_file(path_text: str, label: str) -> Path:
    if not str(path_text).strip():
        raise ValueError(f"{label} is required")
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path.resolve()


def resolve_mfx_path(path_text: str) -> Path:
    bundled = TOOLS_DIR / "ShaderPackage.mfx"
    candidates: list[Path] = []
    if str(path_text).strip():
        candidates.append(Path(path_text).expanduser())
    candidates.append(bundled)
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved
    tried = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        "MFX not found. Copy ShaderPackage.mfx into the add-on folder "
        f"({bundled}) or set it in the GBM Setup panel. Tried: {tried}"
    )


def safe_name(value: str, fallback: str = "gbm_asset") -> str:
    allowed = []
    for char in value.strip():
        allowed.append(char if char.isalnum() or char in "._-" else "_")
    cleaned = "".join(allowed).strip("._ ")
    return cleaned or fallback


def export_extension(format_name: str) -> str:
    normalized = format_name.lower()
    if normalized == "fbx":
        return ".fbx"
    if normalized in {"glb", "gltf"}:
        return ".glb"
    if normalized == "obj":
        return ".obj"
    raise ValueError(f"unsupported export format: {format_name}")


def export_path(output_dir: Path, name: str, format_name: str) -> Path:
    return output_dir / f"{safe_name(name)}{export_extension(format_name)}"


def resolve_lookup_arcs(
    *,
    kind: str,
    serial: str,
    archive_root: Path,
    contains: bool = False,
    limit: int | None = None,
) -> list[Path]:
    import gbm_lookup_export

    csv_path = gbm_lookup_export.lookup_csv_for_kind(kind, None)
    entries = gbm_lookup_export.read_lookup_entries(
        csv_path=csv_path,
        archive_root=archive_root,
        kind=kind,
        serial_filters=[serial],
        contains=contains,
        limit=limit,
    )
    return [entry.archive_path for entry in entries]


def iter_unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique = []
    for path in paths:
        resolved = path.resolve()
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def copy_file_once(source: Path, output_dir: Path) -> Path:
    source = source.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = (output_dir / source.name).resolve()
    if source != destination:
        shutil.copy2(source, destination)
    return destination


def run_tool(python_exe: str, script_name: str, args: list[str]) -> None:
    command = [python_exe, str(TOOLS_DIR / script_name), *args]
    subprocess.run(command, check=True)


def prepare_imports_from_arcs(
    arc_paths: Iterable[Path],
    *,
    work_root: Path,
    mfx_path: Path,
    lod: int,
    python_exe: str | None = None,
) -> list[PreparedImport]:
    from gbm_blender_convert import BlenderConversionJob
    from gbm_start import select_mod_paths, texture_source_dirs, unique_model_directory_names

    if python_exe is None:
        import gbm_arc_extract
        import gbm_tex_to_png
        from gbm_mod_obj_probe import write_obj_probe
    else:
        write_obj_probe = None

    prepared: list[PreparedImport] = []
    work_root.mkdir(parents=True, exist_ok=True)
    for arc_path in iter_unique_paths(arc_paths):
        arc_root = work_root / safe_name(arc_path.stem)
        extracted_dir = arc_root / "extracted"
        if python_exe is None:
            gbm_arc_extract.main(
                [
                    str(arc_path),
                    "-o",
                    str(extracted_dir),
                    "--no-manifest",
                    "--model-assets-only",
                ]
            )
        else:
            run_tool(
                python_exe,
                "gbm_arc_extract.py",
                [
                    str(arc_path),
                    "-o",
                    str(extracted_dir),
                    "--no-manifest",
                    "--model-assets-only",
                ],
            )
        mod_paths = select_mod_paths({}, extracted_dir, model_stem=None)
        model_names = unique_model_directory_names(mod_paths)
        png_dir = arc_root / "models" / "png"
        tex_manifest = png_dir / "_tex_manifest.json"
        for source_dir in texture_source_dirs(mod_paths, extracted_dir):
            if python_exe is None:
                gbm_tex_to_png.main(
                    [str(source_dir), "-o", str(png_dir), "--manifest", str(tex_manifest)]
                )
            else:
                run_tool(
                    python_exe,
                    "gbm_tex_to_png.py",
                    [str(source_dir), "-o", str(png_dir), "--manifest", str(tex_manifest)],
                )
        for mod_path in mod_paths:
            mrl_path = mod_path.with_suffix(".mrl")
            if not mrl_path.exists():
                raise FileNotFoundError(f"MRL not found for {mod_path}: {mrl_path}")
            model_stem = mod_path.stem
            model_root = arc_root / "models" / model_names[mod_path]
            obj_path = model_root / "obj" / f"{model_stem}.obj"
            manifest_path = model_root / "obj" / f"{model_stem}_obj_manifest.json"
            if python_exe is None:
                write_obj_probe(
                    mod_path,
                    mfx_path,
                    obj_path,
                    manifest_path,
                    "bind-pose",
                    "engine",
                    None,
                    lod,
                    mrl_path,
                    png_dir,
                )
            else:
                run_tool(
                    python_exe,
                    "gbm_mod_obj_probe.py",
                    [
                        str(mod_path),
                        "--mfx",
                        str(mfx_path),
                        "-o",
                        str(obj_path),
                        "--manifest",
                        str(manifest_path),
                        "--position-mode",
                        "bind-pose",
                        "--axis-mode",
                        "engine",
                        "--lod",
                        str(lod),
                        "--mrl",
                        str(mrl_path),
                        "--png-dir",
                        str(png_dir),
                    ],
                )
            job = BlenderConversionJob(
                input_obj=obj_path,
                output_fbx=model_root / "fbx" / f"{model_stem}.fbx",
                mrl=mrl_path,
                png_dir=png_dir,
                mod=mod_path,
                mfx=mfx_path,
                lod=lod,
            )
            prepared.append(
                PreparedImport(
                    arc_path=arc_path,
                    model_stem=model_stem,
                    collection_name=f"GBM_{safe_name(arc_path.stem)}_{safe_name(model_stem)}",
                    job=job,
                )
            )
    return prepared
