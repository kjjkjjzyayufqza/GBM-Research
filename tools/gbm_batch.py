#!/usr/bin/env python3
"""Batch extract GBM ARC folders and batch export model assets."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "out" / "batch"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from gbm_start import (  # noqa: E402
    DEFAULT_BLENDER,
    DEFAULT_MFX,
    BlenderJob,
    add_export_options,
    arc_extract_command,
    convert_model_textures,
    obj_probe_command,
    run_blender_batch,
    run_command,
    select_mod_paths,
    unique_model_directory_names,
)


@dataclass(frozen=True)
class ModelExport:
    arc: Path
    model_stem: str
    model_output_root: Path
    mod: Path
    mrl: Path
    obj: Path
    fbx: Path | None
    preview: Path | None
    report: Path | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Batch extract GBM .arc files or export every model found in an ARC "
            "folder tree."
        )
    )
    parser.add_argument(
        "inputs",
        metavar="input",
        nargs="+",
        type=Path,
        help=(
            "One or more .arc files or folders containing .arc files. "
            "Drag/drop friendly."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Output root. Defaults to GBM-Research/out/batch/<input-name> for a "
            "single input, or GBM-Research/out/batch for multiple inputs. "
            "Relative ARC folders and ARC stems are preserved below this root."
        ),
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract every ARC into its own folder; do not export models.",
    )
    parser.add_argument(
        "--format",
        choices=("obj", "fbx"),
        default="fbx",
        help="Export OBJ only, or OBJ plus FBX. Defaults to fbx.",
    )
    parser.add_argument(
        "--mfx",
        type=Path,
        default=DEFAULT_MFX,
        help=f"ShaderPackage.mfx used for MOD layouts. Defaults to {DEFAULT_MFX}.",
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=DEFAULT_BLENDER,
        help=f"Blender executable for FBX export. Defaults to {DEFAULT_BLENDER}.",
    )
    add_export_options(parser)
    parser.add_argument(
        "--limit",
        type=int,
        help="Pass through to gbm_arc_extract.py for partial extraction.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned commands without executing them.",
    )
    return parser.parse_args()


def iter_arc_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".arc":
            raise ValueError(f"input file is not an .arc archive: {input_path}")
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"input path does not exist: {input_path}")
    arcs = sorted(input_path.rglob("*.arc"), key=lambda path: str(path).lower())
    if not arcs:
        raise FileNotFoundError(f"no .arc files found under {input_path}")
    return arcs


def resolve_output_root(
    input_paths: list[Path], requested_output: Path | None
) -> Path:
    if requested_output:
        return requested_output.resolve()
    if len(input_paths) == 1:
        return (DEFAULT_OUTPUT_ROOT / input_paths[0].stem).resolve()
    return DEFAULT_OUTPUT_ROOT.resolve()


def arc_output_root(input_root: Path, output_root: Path, arc_path: Path) -> Path:
    if input_root == arc_path or input_root.suffix.lower() == ".arc":
        return output_root / arc_path.stem
    relative = arc_path.relative_to(input_root).with_suffix("")
    return output_root / relative


def prepare_model_export(
    arc_path: Path,
    model_root: Path,
    png_dir: Path,
    mod_path: Path,
    mfx_path: Path,
    export_format: str,
    lod: int,
    want_preview: bool,
    want_report: bool,
) -> tuple[ModelExport | None, BlenderJob | None]:
    model_stem = mod_path.stem
    obj_dir = model_root / "obj"
    fbx_dir = model_root / "fbx"
    obj_path = obj_dir / f"{model_stem}.obj"
    obj_manifest_path = obj_dir / f"{model_stem}_obj_manifest.json"

    mrl_path = mod_path.with_suffix(".mrl")
    if not mrl_path.exists():
        raise FileNotFoundError(f"MRL not found for {mod_path}: {mrl_path}")

    run_command(
        obj_probe_command(
            mod_path, mfx_path, mrl_path, png_dir, obj_path, obj_manifest_path, lod
        ),
        dry_run=False,
    )

    blender_job = None
    fbx_path = None
    preview_path = None
    report_path = None
    if export_format == "fbx":
        fbx_path = fbx_dir / f"{model_stem}.fbx"
        preview_path = fbx_dir / f"{model_stem}_preview.png" if want_preview else None
        report_path = (
            fbx_dir / f"{model_stem}_fbx_report.json" if want_report else None
        )
        # The converter needs the MOD for material name mapping in every case
        # and decides skin binding itself from the MOD bone count.
        blender_job = BlenderJob(
            input_obj=obj_path,
            output_fbx=fbx_path,
            lod=lod,
            mrl=mrl_path,
            png_dir=png_dir,
            mod=mod_path,
            mfx=mfx_path,
            preview=preview_path,
            report=report_path,
        )

    return (
        ModelExport(
            arc=arc_path,
            model_stem=model_stem,
            model_output_root=model_root,
            mod=mod_path,
            mrl=mrl_path,
            obj=obj_path,
            fbx=fbx_path,
            preview=preview_path,
            report=report_path,
        ),
        blender_job,
    )


def extract_only(
    input_path: Path,
    output_root: Path,
    arcs: list[Path],
    limit: int | None,
    dry_run: bool,
) -> list[dict[str, str]]:
    results = []
    for arc_path in arcs:
        arc_root = arc_output_root(input_path, output_root, arc_path)
        manifest_path = arc_root / "_manifest.json"
        run_command(
            arc_extract_command(arc_path, arc_root, manifest_path, limit), dry_run
        )
        results.append(
            {
                "arc": str(arc_path),
                "output": str(arc_root),
                "manifest": str(manifest_path),
            }
        )
    return results


def export_all_models(
    input_path: Path,
    output_root: Path,
    arcs: list[Path],
    mfx_path: Path,
    export_format: str,
    lod: int,
    want_preview: bool,
    want_report: bool,
    limit: int | None,
    dry_run: bool,
) -> tuple[list[ModelExport], list[BlenderJob], list[dict[str, str]]]:
    model_exports: list[ModelExport] = []
    blender_jobs: list[BlenderJob] = []
    failures: list[dict[str, str]] = []
    for arc_path in arcs:
        arc_root = arc_output_root(input_path, output_root, arc_path)
        extracted_dir = arc_root / "extracted"
        run_command(
            arc_extract_command(
                arc_path,
                extracted_dir,
                limit=limit,
                model_assets_only=True,
                write_manifest=False,
            ),
            dry_run,
        )
        if dry_run:
            continue

        try:
            mod_paths = select_mod_paths({}, extracted_dir, model_stem=None)
        except FileNotFoundError as exc:
            print(f"warning: skipped {arc_path}: {exc}", file=sys.stderr)
            continue
        model_names = unique_model_directory_names(mod_paths)
        png_dir = arc_root / "models" / "png"
        convert_model_textures(
            png_dir, mod_paths, dry_run=False, extracted_dir=extracted_dir
        )
        for mod_path in mod_paths:
            try:
                model_export, blender_job = prepare_model_export(
                    arc_path=arc_path,
                    model_root=arc_root / "models" / model_names[mod_path],
                    png_dir=png_dir,
                    mod_path=mod_path,
                    mfx_path=mfx_path,
                    export_format=export_format,
                    lod=lod,
                    want_preview=want_preview,
                    want_report=want_report,
                )
            except Exception as exc:
                failure = {
                    "arc": str(arc_path),
                    "mod": str(mod_path),
                    "error": str(exc),
                }
                failures.append(failure)
                print(f"warning: skipped {mod_path}: {exc}", file=sys.stderr)
                continue
            if model_export:
                model_exports.append(model_export)
            if blender_job:
                blender_jobs.append(blender_job)
    return model_exports, blender_jobs, failures


def write_summary(
    output_root: Path,
    input_paths: list[Path],
    extract_results: list[dict[str, str]],
    model_exports: list[ModelExport],
    blender_jobs: list[BlenderJob],
    failures: list[dict[str, str]],
    dry_run: bool,
) -> None:
    summary = {
        "inputs": [str(input_path) for input_path in input_paths],
        "output_root": str(output_root),
        "extracted_arc_count": len(extract_results),
        "model_count": len(model_exports),
        "fbx_job_count": len(blender_jobs),
        "failure_count": len(failures),
        "extractions": extract_results,
        "models": [asdict(model_export) for model_export in model_exports],
        "failures": failures,
    }
    summary_path = output_root / "_gbm_batch_manifest.json"
    if not dry_run:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, default=str))


def main() -> int:
    args = parse_args()
    input_paths = [input_path.resolve() for input_path in args.inputs]
    output_root = resolve_output_root(input_paths, args.output)
    mfx_path = args.mfx.resolve()
    if not args.extract_only and not mfx_path.exists():
        raise FileNotFoundError(f"MFX file not found: {mfx_path}")

    if not args.dry_run:
        output_root.mkdir(parents=True, exist_ok=True)

    extract_results: list[dict[str, str]] = []
    model_exports: list[ModelExport] = []
    blender_jobs: list[BlenderJob] = []
    failures: list[dict[str, str]] = []

    for input_path in input_paths:
        arcs = iter_arc_files(input_path)
        if args.extract_only:
            extract_results.extend(
                extract_only(
                    input_path=input_path,
                    output_root=output_root,
                    arcs=arcs,
                    limit=args.limit,
                    dry_run=args.dry_run,
                )
            )
            continue

        batch_exports, batch_jobs, batch_failures = export_all_models(
            input_path=input_path,
            output_root=output_root,
            arcs=arcs,
            mfx_path=mfx_path,
            export_format=args.format,
            lod=args.lod,
            want_preview=args.preview,
            want_report=args.report,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        model_exports.extend(batch_exports)
        blender_jobs.extend(batch_jobs)
        failures.extend(batch_failures)

    if not args.extract_only:
        run_blender_batch(
            output_root=output_root,
            blender_path=args.blender.resolve(),
            jobs=blender_jobs,
            dry_run=args.dry_run,
        )

    write_summary(
        output_root,
        input_paths,
        extract_results,
        model_exports,
        blender_jobs,
        failures,
        args.dry_run,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
