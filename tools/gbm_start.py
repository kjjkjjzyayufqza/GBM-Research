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
        help="Prefer a MOD/TEX stem, for example ma320900. Defaults to first MOD.",
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
    return parser.parse_args()


def build_paths(output_root: Path, model_stem: str) -> PipelinePaths:
    extracted_dir = output_root / "extracted"
    png_dir = output_root / "png"
    obj_dir = output_root / "obj"
    fbx_dir = output_root / "fbx"
    return PipelinePaths(
        output_root=output_root,
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


def choose_mod_path(
    manifest: dict[str, object],
    extracted_dir: Path,
    model_stem: str | None,
) -> Path:
    manifest_mods = [
        output
        for output in entry_output_paths(manifest)
        if output.suffix.lower() == ".mod"
    ]
    disk_mods = sorted(extracted_dir.rglob("*.mod"))
    candidates = manifest_mods or disk_mods
    if not candidates:
        raise FileNotFoundError(f"No .mod file found under {extracted_dir}")

    if model_stem:
        matches = [path for path in candidates if path.stem == model_stem]
        if not matches:
            raise FileNotFoundError(
                f"No .mod matching --model-stem {model_stem!r} found"
            )
        return matches[0]
    return sorted(candidates, key=lambda path: str(path).lower())[0]


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
) -> None:
    if not model_stem:
        print(
            "Dry run stopped after ARC extraction planning because --model-stem "
            "was not provided. The real run will choose the first extracted .mod "
            "from the manifest."
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
            "blender",
            "--manifest",
            str(paths.obj_manifest_path),
        ],
    ):
        print(format_command(command))

    if skip_fbx:
        return

    print(
        format_command(
            [
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
                "--preview",
                str(paths.preview_path),
                "--report",
                str(paths.fbx_report_path),
            ]
        )
    )


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
        )
        print(json.dumps({"planned": asdict(paths)}, indent=2, default=str))
        return 0

    manifest = load_manifest(paths.manifest_path)
    mod_path = choose_mod_path(manifest, paths.extracted_dir, args.model_stem)
    model_stem = mod_path.stem
    paths = build_paths(output_root, model_stem)

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
        args.dry_run,
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
        "blender",
        "--manifest",
        str(paths.obj_manifest_path),
    ]
    run_command(obj_command, args.dry_run)

    result: dict[str, str | None] = {
        "arc": str(arc_path),
        "mfx": str(mfx_path),
        "mod": str(mod_path),
        "base_texture": str(base_texture),
        "normal_texture": str(normal_texture) if normal_texture else None,
        "obj": str(paths.obj_path),
        "fbx": None,
        "preview": None,
        "report": None,
    }

    if args.skip_fbx:
        print(json.dumps(result, indent=2))
        return 0

    blender_path = args.blender.resolve()
    if not blender_path.exists():
        raise FileNotFoundError(
            f"Blender executable not found: {blender_path}. "
            "Use --blender or --skip-fbx."
        )

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
        "--preview",
        str(paths.preview_path),
        "--report",
        str(paths.fbx_report_path),
    ]
    if normal_texture:
        blender_command.extend(["--normal-texture", str(normal_texture)])
    run_command(blender_command, args.dry_run)

    result.update(
        {
            "fbx": str(paths.fbx_path),
            "preview": str(paths.preview_path),
            "report": str(paths.fbx_report_path),
        }
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
