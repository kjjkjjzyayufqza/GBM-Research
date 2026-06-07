#!/usr/bin/env python3
"""Run the GBM static extraction pipeline.

This is a thin orchestrator around the focused research tools in this
directory. It intentionally keeps format logic in the lower-level scripts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe")
TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_MFX = TOOLS_DIR / "ShaderPackage.mfx"


@dataclass
class PipelinePaths:
    output_root: Path
    artifact_root: Path
    extracted_dir: Path
    png_dir: Path
    obj_dir: Path
    fbx_dir: Path
    manifest_path: Path
    tex_manifest_path: Path
    obj_manifest_path: Path
    fbx_report_path: Path
    preview_path: Path
    obj_path: Path
    fbx_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the GBM static ARC -> PNG/OBJ/FBX extraction pipeline."
    )
    parser.add_argument("arc", type=Path, help="Input GBM .arc archive")
    parser.add_argument(
        "--mfx",
        type=Path,
        default=DEFAULT_MFX,
        help=(
            "ShaderPackage.mfx used for MOD vertex input layouts. "
            f"Defaults to {DEFAULT_MFX}."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output root. Defaults to out/<arc-stem>",
    )
    parser.add_argument(
        "--model-stem",
        help=(
            "Limit export to one MOD/TEX stem, for example ma320900. "
            "When omitted, every discovered .mod is exported."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Pass through to gbm_arc_extract.py for partial extraction",
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=DEFAULT_BLENDER,
        help=f"Blender executable. Defaults to {DEFAULT_BLENDER}",
    )
    parser.add_argument(
        "--skip-fbx",
        action="store_true",
        help="Stop after TEX->PNG and MOD->OBJ; do not call Blender.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete the output root before running.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands and planned outputs without executing.",
    )
    parser.add_argument(
        "--lod",
        type=int,
        choices=(0, 1, 2),
        default=0,
        help="LOD level for OBJ and FBX export. 0 is highest detail.",
    )
    return parser.parse_args()


def build_paths(
    output_root: Path, model_stem: str, artifact_root: Path | None = None
) -> PipelinePaths:
    extracted_dir = output_root / "extracted"
    artifact_root = artifact_root or output_root
    png_dir = artifact_root / "png"
    obj_dir = artifact_root / "obj"
    fbx_dir = artifact_root / "fbx"
    return PipelinePaths(
        output_root=output_root,
        artifact_root=artifact_root,
        extracted_dir=extracted_dir,
        png_dir=png_dir,
        obj_dir=obj_dir,
        fbx_dir=fbx_dir,
        manifest_path=extracted_dir / "_manifest.json",
        tex_manifest_path=png_dir / "_tex_manifest.json",
        obj_manifest_path=obj_dir / f"{model_stem}_obj_manifest.json",
        fbx_report_path=fbx_dir / f"{model_stem}_fbx_report.json",
        preview_path=fbx_dir / f"{model_stem}_preview.png",
        obj_path=obj_dir / f"{model_stem}.obj",
        fbx_path=fbx_dir / f"{model_stem}.fbx",
    )


def run_command(command: list[str], dry_run: bool) -> None:
    print(format_command(command))
    if dry_run:
        return
    subprocess.run(command, check=True)


def format_command(command: list[str]) -> str:
    return " ".join(quote_argument(part) for part in command)


def quote_argument(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        return f'"{value}"'
    return value


def remove_output_root(path: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    if resolved == cwd or cwd not in resolved.parents:
        raise ValueError(f"Refusing to remove output outside current repo: {resolved}")
    shutil.rmtree(resolved)


def load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Archive manifest was not written: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def entry_output_paths(manifest: dict[str, object]) -> list[Path]:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Manifest does not contain an entries list")
    outputs = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("output"), str):
            outputs.append(Path(entry["output"]))
    return outputs


def select_mod_paths(
    manifest: dict[str, object],
    extracted_dir: Path,
    model_stem: str | None,
) -> list[Path]:
    manifest_mods = [
        output
        for output in entry_output_paths(manifest)
        if output.suffix.lower() == ".mod"
    ]
    disk_mods = sorted(extracted_dir.rglob("*.mod"))
    candidates = sorted(
        {path for path in (manifest_mods or disk_mods)},
        key=lambda path: str(path).lower(),
    )
    if not candidates:
        raise FileNotFoundError(f"No .mod file found under {extracted_dir}")

    if model_stem:
        matches = [path for path in candidates if path.stem == model_stem]
        if not matches:
            raise FileNotFoundError(
                f"No .mod matching --model-stem {model_stem!r} found"
            )
        if len(matches) > 1:
            choices = "\n".join(f"  - {path}" for path in matches)
            raise FileNotFoundError(
                f"Multiple .mod files match --model-stem {model_stem!r}:\n{choices}"
            )
        return [matches[0]]
    return candidates


def unique_model_directory_names(mod_paths: list[Path]) -> dict[Path, str]:
    counts: dict[str, int] = {}
    for mod_path in mod_paths:
        counts[mod_path.stem] = counts.get(mod_path.stem, 0) + 1

    seen: dict[str, int] = {}
    directory_names: dict[Path, str] = {}
    for mod_path in mod_paths:
        stem = mod_path.stem
        if counts[stem] == 1:
            directory_names[mod_path] = stem
            continue
        seen[stem] = seen.get(stem, 0) + 1
        if seen[stem] == 1:
            directory_names[mod_path] = stem
            continue
        directory_names[mod_path] = f"{stem}__{seen[stem]}"
    return directory_names


def choose_texture(
    png_dir: Path,
    model_stem: str,
    suffix: str,
) -> Path | None:
    preferred = png_dir / f"{model_stem}_{suffix}.png"
    if preferred.exists():
        return preferred
    matches = sorted(png_dir.rglob(f"*_{suffix}.png"))
    return matches[0] if matches else None


def print_planned_followup_commands(
    paths: PipelinePaths,
    model_stem: str | None,
    mfx_path: Path,
    blender_path: Path,
    skip_fbx: bool,
    lod: int,
) -> None:
    if not model_stem:
        print(
            "Dry run stopped after ARC extraction planning because the final .mod "
            "list is only known after extraction. The real run will export every "
            "discovered .mod into output_root\\models\\<unique-model-name>."
        )
        return

    assumed_mod = (
        paths.extracted_dir
        / "character"
        / model_stem
        / "mod"
        / f"{model_stem}.mod"
    )
    base_texture = paths.png_dir / f"{model_stem}_BM.png"
    normal_texture = paths.png_dir / f"{model_stem}_NM.png"

    for command in (
        [
            sys.executable,
            str(TOOLS_DIR / "gbm_tex_to_png.py"),
            str(assumed_mod.parent),
            "-o",
            str(paths.png_dir),
            "--manifest",
            str(paths.tex_manifest_path),
        ],
        [
            sys.executable,
            str(TOOLS_DIR / "gbm_mod_obj_probe.py"),
            str(assumed_mod),
            "--mfx",
            str(mfx_path),
            "-o",
            str(paths.obj_path),
            "--texture",
            str(base_texture),
            "--position-mode",
            "bind-pose",
            "--axis-mode",
            "engine",
            "--lod",
            str(lod),
            "--manifest",
            str(paths.obj_manifest_path),
        ],
    ):
        print(format_command(command))

    if skip_fbx:
        return

    blender_command = [
        str(blender_path),
        "--background",
        "--python",
        str(TOOLS_DIR / "gbm_blender_convert.py"),
        "--",
        "--input-obj",
        str(paths.obj_path),
        "--output-fbx",
        str(paths.fbx_path),
        "--texture",
        str(base_texture),
        "--normal-texture",
        str(normal_texture),
        "--mod",
        str(assumed_mod),
        "--mfx",
        str(mfx_path),
        "--lod",
        str(lod),
        "--preview",
        str(paths.preview_path),
        "--report",
        str(paths.fbx_report_path),
    ]
    print(format_command(blender_command))


def run_model_pipeline(
    output_root: Path,
    mod_path: Path,
    model_directory_name: str | None,
    mfx_path: Path,
    blender_path: Path,
    skip_fbx: bool,
    lod: int,
) -> dict[str, str | int | None]:
    model_stem = mod_path.stem
    artifact_root = (
        output_root / "models" / model_directory_name
        if model_directory_name is not None
        else output_root
    )
    paths = build_paths(output_root, model_stem, artifact_root=artifact_root)

    run_command(
        [
            sys.executable,
            str(TOOLS_DIR / "gbm_tex_to_png.py"),
            str(mod_path.parent),
            "-o",
            str(paths.png_dir),
            "--manifest",
            str(paths.tex_manifest_path),
        ],
        dry_run=False,
    )

    base_texture = choose_texture(paths.png_dir, model_stem, "BM")
    normal_texture = choose_texture(paths.png_dir, model_stem, "NM")
    if base_texture is None:
        raise FileNotFoundError(
            f"No base-color PNG matching {model_stem}_BM.png found in {paths.png_dir}"
        )

    obj_command = [
        sys.executable,
        str(TOOLS_DIR / "gbm_mod_obj_probe.py"),
        str(mod_path),
        "--mfx",
        str(mfx_path),
        "-o",
        str(paths.obj_path),
        "--texture",
        str(base_texture),
        "--position-mode",
        "bind-pose",
        "--axis-mode",
        "engine",
        "--lod",
        str(lod),
        "--manifest",
        str(paths.obj_manifest_path),
    ]
    run_command(obj_command, dry_run=False)

    result: dict[str, str | int | None] = {
        "model_stem": model_stem,
        "model_output_root": str(paths.artifact_root),
        "mod": str(mod_path),
        "lod": lod,
        "base_texture": str(base_texture),
        "normal_texture": str(normal_texture) if normal_texture else None,
        "obj": str(paths.obj_path),
        "fbx": None,
        "preview": None,
        "report": None,
    }

    if skip_fbx:
        return result

    blender_command = [
        str(blender_path),
        "--background",
        "--python",
        str(TOOLS_DIR / "gbm_blender_convert.py"),
        "--",
        "--input-obj",
        str(paths.obj_path),
        "--output-fbx",
        str(paths.fbx_path),
        "--texture",
        str(base_texture),
        "--mod",
        str(mod_path),
        "--mfx",
        str(mfx_path),
        "--lod",
        str(lod),
        "--preview",
        str(paths.preview_path),
        "--report",
        str(paths.fbx_report_path),
    ]
    if normal_texture:
        blender_command.extend(["--normal-texture", str(normal_texture)])
    run_command(blender_command, dry_run=False)
    result.update(
        {
            "fbx": str(paths.fbx_path),
            "preview": str(paths.preview_path),
            "report": str(paths.fbx_report_path),
        }
    )
    return result


def main() -> int:
    args = parse_args()
    arc_path = args.arc.resolve()
    mfx_path = args.mfx.resolve()
    if not arc_path.exists():
        raise FileNotFoundError(f"ARC file not found: {arc_path}")
    if not mfx_path.exists():
        raise FileNotFoundError(
            f"MFX file not found: {mfx_path}. Copy ShaderPackage.mfx to "
            "tools\\ShaderPackage.mfx or pass --mfx <path>."
        )

    output_root = (args.output or Path("out") / arc_path.stem).resolve()
    if args.force and not args.dry_run:
        remove_output_root(output_root)

    provisional_stem = args.model_stem or arc_path.stem
    paths = build_paths(output_root, provisional_stem)

    extract_command = [
        sys.executable,
        str(TOOLS_DIR / "gbm_arc_extract.py"),
        str(arc_path),
        "-o",
        str(paths.extracted_dir),
        "--manifest",
        str(paths.manifest_path),
    ]
    if args.limit is not None:
        extract_command.extend(["--limit", str(args.limit)])
    run_command(extract_command, args.dry_run)
    if args.dry_run:
        print_planned_followup_commands(
            paths,
            args.model_stem,
            mfx_path,
            args.blender.resolve(),
            args.skip_fbx,
            args.lod,
        )
        print(json.dumps({"planned": asdict(paths)}, indent=2, default=str))
        return 0

    blender_path = args.blender.resolve()
    if not args.skip_fbx and not blender_path.exists():
        raise FileNotFoundError(
            f"Blender executable not found: {blender_path}. "
            "Use --blender or --skip-fbx."
        )

    manifest = load_manifest(paths.manifest_path)
    mod_paths = select_mod_paths(manifest, paths.extracted_dir, args.model_stem)
    model_directory_names = (
        unique_model_directory_names(mod_paths) if args.model_stem is None else {}
    )
    results = [
        run_model_pipeline(
            output_root=output_root,
            mod_path=mod_path,
            model_directory_name=model_directory_names.get(mod_path),
            mfx_path=mfx_path,
            blender_path=blender_path,
            skip_fbx=args.skip_fbx,
            lod=args.lod,
        )
        for mod_path in mod_paths
    ]

    if len(results) == 1:
        result = dict(results[0])
        result.update({"arc": str(arc_path), "mfx": str(mfx_path)})
        print(json.dumps(result, indent=2))
        return 0

    print(
        json.dumps(
            {
                "arc": str(arc_path),
                "mfx": str(mfx_path),
                "output_root": str(output_root),
                "model_count": len(results),
                "models": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
