#!/usr/bin/env python3
"""Run the GBM static extraction pipeline.

This is a thin orchestrator around the focused research tools in this
directory. It intentionally keeps format logic in the lower-level scripts and
exposes the shared pipeline building blocks that gbm_batch.py reuses.
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


@dataclass(frozen=True)
class BlenderJob:
    input_obj: Path
    output_fbx: Path
    lod: int
    texture: Path | None = None
    normal_texture: Path | None = None
    mrl: Path | None = None
    png_dir: Path | None = None
    mod: Path | None = None
    mfx: Path | None = None
    preview: Path | None = None
    report: Path | None = None


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
    add_export_options(parser)
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


def add_export_options(parser: argparse.ArgumentParser) -> None:
    """Register the LOD and optional preview/report flags shared by both CLIs."""
    parser.add_argument(
        "--lod",
        type=int,
        choices=(0, 1, 2),
        default=0,
        help="LOD level for OBJ and FBX export. 0 is highest detail.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render a preview PNG next to each FBX. Off by default.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write an FBX validation report JSON next to each FBX. Off by default.",
    )


def build_paths(
    output_root: Path,
    model_stem: str,
    artifact_root: Path | None = None,
    png_dir: Path | None = None,
) -> PipelinePaths:
    extracted_dir = output_root / "extracted"
    artifact_root = artifact_root or output_root
    png_dir = png_dir or (artifact_root / "png")
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
    print(format_command(command), flush=True)
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


def arc_extract_command(
    arc_path: Path,
    extracted_dir: Path,
    manifest_path: Path,
    limit: int | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(TOOLS_DIR / "gbm_arc_extract.py"),
        str(arc_path),
        "-o",
        str(extracted_dir),
        "--manifest",
        str(manifest_path),
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])
    return command


def tex_to_png_command(
    mod_dir: Path,
    png_dir: Path,
    manifest_path: Path,
) -> list[str]:
    return [
        sys.executable,
        str(TOOLS_DIR / "gbm_tex_to_png.py"),
        str(mod_dir),
        "-o",
        str(png_dir),
        "--manifest",
        str(manifest_path),
    ]


def obj_probe_command(
    mod_path: Path,
    mfx_path: Path,
    mrl_path: Path,
    png_dir: Path,
    obj_path: Path,
    manifest_path: Path,
    lod: int,
) -> list[str]:
    return [
        sys.executable,
        str(TOOLS_DIR / "gbm_mod_obj_probe.py"),
        str(mod_path),
        "--mfx",
        str(mfx_path),
        "-o",
        str(obj_path),
        "--mrl",
        str(mrl_path),
        "--png-dir",
        str(png_dir),
        "--position-mode",
        "bind-pose",
        "--axis-mode",
        "engine",
        "--lod",
        str(lod),
        "--manifest",
        str(manifest_path),
    ]


def blender_batch_command(blender_path: Path, manifest_path: Path) -> list[str]:
    return [
        str(blender_path),
        "--background",
        "--python",
        str(TOOLS_DIR / "gbm_blender_convert.py"),
        "--",
        "--batch-manifest",
        str(manifest_path),
    ]


def blender_job_record(job: BlenderJob) -> dict[str, object]:
    return {
        "input_obj": str(job.input_obj),
        "output_fbx": str(job.output_fbx),
        "texture": str(job.texture) if job.texture else None,
        "normal_texture": str(job.normal_texture) if job.normal_texture else None,
        "mrl": str(job.mrl) if job.mrl else None,
        "png_dir": str(job.png_dir) if job.png_dir else None,
        "mod": str(job.mod) if job.mod else None,
        "mfx": str(job.mfx) if job.mfx else None,
        "lod": job.lod,
        "preview": str(job.preview) if job.preview else None,
        "report": str(job.report) if job.report else None,
    }


def run_blender_batch(
    output_root: Path,
    blender_path: Path,
    jobs: list[BlenderJob],
    dry_run: bool = False,
) -> None:
    if not jobs:
        return
    if not dry_run and not blender_path.exists():
        raise FileNotFoundError(
            f"Blender executable not found: {blender_path}. "
            "Use --blender, or skip FBX export."
        )
    manifest_path = output_root / "_gbm_blender_jobs.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(json.dumps({"planned_blender_jobs": len(jobs)}, indent=2))
    else:
        manifest_path.write_text(
            json.dumps({"jobs": [blender_job_record(job) for job in jobs]}, indent=2),
            encoding="utf-8",
        )
    run_command(blender_batch_command(blender_path, manifest_path), dry_run)


def convert_model_textures(
    png_dir: Path, mod_paths: list[Path], dry_run: bool
) -> None:
    """Convert each unique MOD directory's TEX into one shared png dir, once.

    Every model in an ARC usually shares a single MOD directory holding all of
    their textures. Converting per model would copy the whole texture set into
    each model folder, so the conversion runs once per unique directory.
    """
    manifest_path = png_dir / "_tex_manifest.json"
    seen: set[Path] = set()
    for mod_path in mod_paths:
        mod_dir = mod_path.parent
        if mod_dir in seen:
            continue
        seen.add(mod_dir)
        run_command(tex_to_png_command(mod_dir, png_dir, manifest_path), dry_run)


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
    assumed_mrl = assumed_mod.with_suffix(".mrl")

    print(
        format_command(
            tex_to_png_command(assumed_mod.parent, paths.png_dir, paths.tex_manifest_path)
        )
    )
    print(
        format_command(
            obj_probe_command(
                assumed_mod,
                mfx_path,
                assumed_mrl,
                paths.png_dir,
                paths.obj_path,
                paths.obj_manifest_path,
                lod,
            )
        )
    )
    if skip_fbx:
        return
    print(
        format_command(
            blender_batch_command(
                blender_path, paths.output_root / "_gbm_blender_jobs.json"
            )
        )
    )


def run_model_pipeline(
    output_root: Path,
    mod_path: Path,
    model_directory_name: str | None,
    png_dir: Path,
    mfx_path: Path,
    lod: int,
    skip_fbx: bool,
    want_preview: bool,
    want_report: bool,
) -> dict[str, object]:
    model_stem = mod_path.stem
    artifact_root = (
        output_root / "models" / model_directory_name
        if model_directory_name is not None
        else output_root
    )
    paths = build_paths(
        output_root, model_stem, artifact_root=artifact_root, png_dir=png_dir
    )

    mrl_path = mod_path.with_suffix(".mrl")
    if not mrl_path.exists():
        raise FileNotFoundError(f"MRL not found for {mod_path}: {mrl_path}")

    run_command(
        obj_probe_command(
            mod_path,
            mfx_path,
            mrl_path,
            paths.png_dir,
            paths.obj_path,
            paths.obj_manifest_path,
            lod,
        ),
        dry_run=False,
    )

    result: dict[str, object] = {
        "model_stem": model_stem,
        "model_output_root": str(paths.artifact_root),
        "mod": str(mod_path),
        "mrl": str(mrl_path),
        "lod": lod,
        "obj": str(paths.obj_path),
        "fbx": None,
        "preview": None,
        "report": None,
    }
    if skip_fbx:
        return result

    preview = paths.preview_path if want_preview else None
    report = paths.fbx_report_path if want_report else None
    result.update(
        {
            "fbx": str(paths.fbx_path),
            "preview": str(preview) if preview else None,
            "report": str(report) if report else None,
            # The converter needs the MOD for material name mapping in every
            # case and decides skin binding itself from the MOD bone count.
            "_blender_job": BlenderJob(
                input_obj=paths.obj_path,
                output_fbx=paths.fbx_path,
                lod=lod,
                mrl=mrl_path,
                png_dir=paths.png_dir,
                mod=mod_path,
                mfx=mfx_path,
                preview=preview,
                report=report,
            ),
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

    run_command(
        arc_extract_command(arc_path, paths.extracted_dir, paths.manifest_path, args.limit),
        args.dry_run,
    )
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
    if args.model_stem is None:
        model_directory_names = unique_model_directory_names(mod_paths)
        png_dir = output_root / "models" / "png"
    else:
        model_directory_names = {}
        png_dir = output_root / "png"
    convert_model_textures(png_dir, mod_paths, dry_run=False)

    results = []
    blender_jobs: list[BlenderJob] = []
    for mod_path in mod_paths:
        result = run_model_pipeline(
            output_root=output_root,
            mod_path=mod_path,
            model_directory_name=model_directory_names.get(mod_path),
            png_dir=png_dir,
            mfx_path=mfx_path,
            lod=args.lod,
            skip_fbx=args.skip_fbx,
            want_preview=args.preview,
            want_report=args.report,
        )
        blender_job = result.pop("_blender_job", None)
        if isinstance(blender_job, BlenderJob):
            blender_jobs.append(blender_job)
        results.append(result)

    run_blender_batch(output_root, blender_path, blender_jobs)

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
