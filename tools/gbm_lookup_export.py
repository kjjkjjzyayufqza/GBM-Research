#!/usr/bin/env python3
"""Export GBM model archives from lookup CSV files into clean named folders."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextvars
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent
WORKSPACE_ROOT = PROJECT_DIR.parent
DEFAULT_ARCHIVE_ROOT = (
    WORKSPACE_ROOT / "com.bandainamcoent.gb_jp" / "files" / "dlc" / "archive"
)
DEFAULT_MODEL_LOOKUP_CSV = TOOLS_DIR / "gbm_archive_lookup_index.csv"
DEFAULT_WEAPON_LOOKUP_CSV = TOOLS_DIR / "gbm_weapon_parts_index.csv"
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "out" / "lookup_exports"
DEFAULT_WORK_ROOT = PROJECT_DIR / "out" / "_lookup_export_work"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import gbm_batch  # noqa: E402
import gbm_start  # noqa: E402
from gbm_batch import export_all_models  # noqa: E402
from gbm_start import (  # noqa: E402
    DEFAULT_BLENDER,
    DEFAULT_MFX,
    BlenderJob,
    add_export_options,
    run_blender_batch,
)


SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
UNDERSCORE_PATTERN = re.compile(r"_+")
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
STATIC_OUTPUT_SUFFIXES = {".obj", ".mtl", ".fbx", ".glb", ".png"}
SKIP_ARCHIVE_SUFFIXES = ("_mot", "_vfx")
PROGRESS_WIDTH = 24
_ACTIVE_COMMAND_TIMINGS: contextvars.ContextVar[list[tuple[str, int]] | None] = (
    contextvars.ContextVar("active_command_timings", default=None)
)
_ACTIVE_PROCESSES_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen] = set()
_CANCEL_REQUESTED = threading.Event()


@dataclass(frozen=True)
class LookupExportEntry:
    serial_name: str
    safe_serial_name: str
    output_name: str
    archive_ref: str
    archive_path: Path
    row_index: int
    model_id: str
    part_type: str


@dataclass(frozen=True)
class ExportRunResult:
    entry_count: int
    model_count: int
    fbx_job_count: int
    failure_count: int
    output_root: Path
    category_root: Path
    total_elapsed_ms: int


@dataclass(frozen=True)
class TimedBlock:
    label: str
    elapsed_ms: int


@dataclass(frozen=True)
class EntryRunResult:
    entry: LookupExportEntry
    elapsed_ms: int
    timings: list[tuple[str, int]]
    jobs: list[BlenderJob]
    failures: list[dict[str, str]]


def sanitize_path_component(value: str, fallback: str = "unnamed") -> str:
    """Return a Windows-safe ASCII directory name for a serial/model name."""

    cleaned = SAFE_NAME_PATTERN.sub("_", value.strip())
    cleaned = UNDERSCORE_PATTERN.sub("_", cleaned).strip(" ._")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:120].rstrip(" ._") or fallback


def split_archive_refs(value: str) -> list[str]:
    refs = []
    for item in value.replace("\\", "/").split(";"):
        ref = item.strip()
        if ref:
            refs.append(ref)
    return refs


def is_static_model_archive(ref: str) -> bool:
    path = Path(ref.replace("\\", "/"))
    if path.suffix.lower() != ".arc":
        return False
    stem = path.stem.lower()
    return not any(stem.endswith(suffix) for suffix in SKIP_ARCHIVE_SUFFIXES)


def row_archive_refs(row: dict[str, str], kind: str) -> list[str]:
    if kind == "model":
        refs = split_archive_refs(row.get("primary_ch_archive", ""))
    else:
        refs = split_archive_refs(row.get("ch_archives", ""))
    return [ref for ref in refs if is_static_model_archive(ref)]


def resolve_archive_path(archive_root: Path, archive_ref: str) -> Path:
    normalized_ref = archive_ref.replace("/", "\\")
    direct_path = archive_root / normalized_ref
    if direct_path.exists():
        return direct_path.resolve()

    filename = Path(archive_ref.replace("\\", "/")).name
    matches = sorted(archive_root.rglob(filename), key=lambda path: str(path).lower())
    if not matches:
        raise FileNotFoundError(f"archive not found for {archive_ref}: {archive_root}")
    return matches[0].resolve()


def serial_matches(
    serial_name: str,
    filters: Sequence[str],
    contains: bool,
) -> bool:
    if not filters:
        return True
    folded = serial_name.casefold()
    if contains:
        return any(item.casefold() in folded for item in filters)
    return any(item.casefold() == folded for item in filters)


def read_lookup_entries(
    csv_path: Path,
    archive_root: Path,
    kind: str,
    serial_filters: Sequence[str] = (),
    contains: bool = False,
    limit: int | None = None,
) -> list[LookupExportEntry]:
    entries: list[LookupExportEntry] = []
    seen: set[tuple[str, str]] = set()
    output_name_counts: dict[str, int] = {}

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader, start=2):
            serial_name = (row.get("serial_name") or "").strip()
            if not serial_name or not serial_matches(
                serial_name, serial_filters, contains
            ):
                continue

            safe_serial_name = sanitize_path_component(serial_name)
            for archive_ref in row_archive_refs(row, kind):
                key = (safe_serial_name.casefold(), archive_ref.casefold())
                if key in seen:
                    continue
                seen.add(key)
                duplicate_index = output_name_counts.get(safe_serial_name.casefold(), 0)
                output_name_counts[safe_serial_name.casefold()] = duplicate_index + 1
                output_name = (
                    safe_serial_name
                    if duplicate_index == 0
                    else f"{safe_serial_name}_{duplicate_index}"
                )
                entries.append(
                    LookupExportEntry(
                        serial_name=serial_name,
                        safe_serial_name=safe_serial_name,
                        output_name=output_name,
                        archive_ref=archive_ref,
                        archive_path=resolve_archive_path(archive_root, archive_ref),
                        row_index=row_index,
                        model_id=(row.get("model_id") or "").strip(),
                        part_type=(row.get("part_type") or "").strip(),
                    )
                )
                if limit is not None and len(entries) >= limit:
                    return entries
    return entries


def ensure_descendant(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"refusing to write outside output root: {resolved_path}")


def reset_directory(path: Path, root: Path) -> None:
    ensure_descendant(path, root)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_allowed_tree(source: Path, destination: Path) -> int:
    copied = 0
    for source_file in sorted(source.rglob("*"), key=lambda path: str(path).lower()):
        if not source_file.is_file():
            continue
        if source_file.suffix.lower() not in STATIC_OUTPUT_SUFFIXES:
            continue
        relative = source_file.relative_to(source)
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        copied += 1
    return copied


def unique_child_path(parent: Path, raw_name: str, used_names: set[str]) -> Path:
    base_name = sanitize_path_component(raw_name, fallback="model")
    candidate = base_name
    index = 2
    while candidate.casefold() in used_names:
        candidate = f"{base_name}__{index}"
        index += 1
    used_names.add(candidate.casefold())
    return parent / candidate


def progress_bar(current: int, total: int) -> str:
    if total <= 0:
        return "-" * PROGRESS_WIDTH
    filled = int(PROGRESS_WIDTH * current / total)
    return "#" * filled + "-" * (PROGRESS_WIDTH - filled)


def print_progress(
    current: int,
    total: int,
    entry: LookupExportEntry,
    stage: str,
    elapsed_ms: int | None = None,
    details: str | None = None,
) -> None:
    suffix = ""
    if elapsed_ms is not None:
        suffix += f" {elapsed_ms}ms"
    if details:
        suffix += f" ({details})"
    print(
        f"[{progress_bar(current, total)}] {current}/{total} "
        f"{entry.safe_serial_name} {entry.archive_ref}: {stage}{suffix}",
        flush=True,
    )


def command_label(command: list[str]) -> str:
    for part in command:
        name = Path(part).name.lower()
        if name == "gbm_arc_extract.py":
            return "extract"
        if name == "gbm_tex_to_png.py":
            return "tex"
        if name == "gbm_mod_obj_probe.py":
            return "obj"
        if name == "gbm_blender_convert.py":
            return "fbx"
    return "command"


def summarize_timings(timings: Iterable[tuple[str, int]]) -> str:
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for label, elapsed_ms in timings:
        totals[label] = totals.get(label, 0) + elapsed_ms
        counts[label] = counts.get(label, 0) + 1
    parts = []
    for label in ("extract", "tex", "obj", "fbx", "copy", "command"):
        if label not in totals:
            continue
        count = counts[label]
        suffix = f"x{count}" if count > 1 else ""
        parts.append(f"{label}{suffix}={totals[label]}ms")
    return ", ".join(parts)


def clear_cancel_request() -> None:
    _CANCEL_REQUESTED.clear()


def _process_is_running(process: subprocess.Popen) -> bool:
    poll = getattr(process, "poll", None)
    if callable(poll):
        return poll() is None
    return getattr(process, "returncode", None) is None


def _kill_process(process: subprocess.Popen) -> None:
    if not _process_is_running(process):
        return
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _register_process(process: subprocess.Popen) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.add(process)


def _unregister_process(process: subprocess.Popen) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.discard(process)


def request_cancel_active_processes() -> None:
    _CANCEL_REQUESTED.set()
    with _ACTIVE_PROCESSES_LOCK:
        processes = list(_ACTIVE_PROCESSES)
    for process in processes:
        _kill_process(process)


@contextmanager
def collect_command_timings() -> Iterable[list[tuple[str, int]]]:
    timings: list[tuple[str, int]] = []
    token = _ACTIVE_COMMAND_TIMINGS.set(timings)
    try:
        yield timings
    finally:
        _ACTIVE_COMMAND_TIMINGS.reset(token)


def quiet_run_command(command: list[str], dry_run: bool) -> None:
    if dry_run:
        print(gbm_start.format_command(command), flush=True)
        return
    if _CANCEL_REQUESTED.is_set():
        raise KeyboardInterrupt

    started = time.perf_counter()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _register_process(process)
        try:
            process.communicate()
        except KeyboardInterrupt:
            request_cancel_active_processes()
            raise
        finally:
            _unregister_process(process)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        active_timings = _ACTIVE_COMMAND_TIMINGS.get()
        if active_timings is not None:
            active_timings.append((command_label(command), elapsed_ms))
        if process.returncode == 0:
            return
        if _CANCEL_REQUESTED.is_set():
            raise KeyboardInterrupt

        log.seek(0)
        lines = log.readlines()
        tail = "".join(lines[-120:])
        print(
            f"failed command: {gbm_start.format_command(command)}\n{tail}",
            file=sys.stderr,
        )
        raise subprocess.CalledProcessError(process.returncode, command)


@contextmanager
def quiet_tool_output(enabled: bool = True):
    if not enabled:
        yield
        return

    original_batch_run_command = gbm_batch.run_command
    original_start_run_command = gbm_start.run_command
    gbm_batch.run_command = quiet_run_command
    gbm_start.run_command = quiet_run_command
    try:
        yield
    finally:
        gbm_batch.run_command = original_batch_run_command
        gbm_start.run_command = original_start_run_command


def materialize_clean_outputs(
    category_root: Path,
    work_root: Path,
    entries: Iterable[LookupExportEntry],
) -> int:
    copied_models = 0
    initialized_outputs: set[str] = set()
    for entry in entries:
        copied_models += materialize_entry_clean_output(
            category_root, work_root, entry, initialized_outputs
        )
    return copied_models


def materialize_entry_clean_output(
    category_root: Path,
    work_root: Path,
    entry: LookupExportEntry,
    initialized_outputs: set[str],
) -> int:
    copied_models = 0
    output_root = category_root.parent
    # All archives of one output entry flatten into a single <output_name>/ folder; each
    # model keeps its own chr stem (e.g. RX-78-2/chr210100, RX-78-2/chr290600).
    # Different archives carry distinct chr stems, so they never collide; any
    # genuine clash is disambiguated by unique_child_path.
    output_key = entry.output_name.casefold()
    arc_models_root = (
        work_root / entry.safe_serial_name / entry.archive_path.stem / "models"
    )
    if not arc_models_root.exists():
        return copied_models

    model_sources = [
        model_source
        for model_source in sorted(
            arc_models_root.iterdir(), key=lambda path: path.name.lower()
        )
        if model_source.is_dir() and model_source.name != "png"
    ]
    if not model_sources:
        return copied_models

    category_root.mkdir(parents=True, exist_ok=True)
    serial_output = category_root / entry.output_name
    if output_key not in initialized_outputs:
        reset_directory(serial_output, output_root)
        initialized_outputs.add(output_key)
    else:
        serial_output.mkdir(parents=True, exist_ok=True)

    png_source = arc_models_root / "png"
    if png_source.exists():
        copy_allowed_tree(png_source, serial_output / "png")

    used_model_names = {
        path.name.casefold()
        for path in serial_output.iterdir()
        if path.is_dir() and path.name != "png"
    }
    for model_source in model_sources:
        model_output = unique_child_path(
            serial_output, model_source.name, used_model_names
        )
        copied = copy_allowed_tree(model_source, model_output)
        if copied:
            copied_models += 1
    return copied_models


def build_parser(default_kind: str | None = None, default_format: str | None = None) -> argparse.ArgumentParser:
    default_engine = "blender" if default_format in {"fbx", "both"} else "native"
    parser = argparse.ArgumentParser(
        description=(
            "Export clean OBJ/FBX/GLB model folders from GBM lookup CSV files. "
            "Final output keeps only OBJ, MTL, FBX, GLB, and PNG files."
        )
    )
    if default_kind is None:
        parser.add_argument(
            "--kind",
            choices=("model", "weapon"),
            required=True,
            help="Use model archive lookup CSV or weapon parts lookup CSV.",
        )
    if default_format is None:
        parser.add_argument(
            "--format",
            default="obj,fbx,gltf",
            help="Native comma-separated output formats: obj,fbx,gltf. Blender accepts obj, fbx, or both.",
        )
    parser.add_argument(
        "--engine",
        choices=("native", "blender"),
        default=default_engine,
        help="native writes OBJ/FBX/GLB in pure Python; blender uses the legacy FBX converter.",
    )
    parser.add_argument(
        "archive_root",
        nargs="?",
        type=Path,
        default=DEFAULT_ARCHIVE_ROOT,
        help=f"Path to files/dlc/archive. Defaults to {DEFAULT_ARCHIVE_ROOT}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root. Defaults to {DEFAULT_OUTPUT_ROOT}.",
    )
    parser.add_argument(
        "--lookup-csv",
        type=Path,
        help="Override lookup CSV path.",
    )
    parser.add_argument(
        "--serial",
        action="append",
        default=[],
        help="Export one serial_name. Repeat for multiple names.",
    )
    parser.add_argument(
        "--contains",
        action="store_true",
        help="Treat --serial values as case-insensitive substrings.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit unique archive exports after CSV filtering.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_ROOT,
        help=(
            "Persistent extraction root for MOD/MRL/TEX/manifests. "
            f"Defaults to {DEFAULT_WORK_ROOT}."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of archives to export concurrently. Defaults to 1. "
            f"Use 2-{min(4, os.cpu_count() or 1)} for faster full exports."
        ),
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
        "--dry-run",
        action="store_true",
        help="Print planned unique archive exports without extracting.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full planned entry JSON and keep child tool command output.",
    )
    parser.set_defaults(default_kind=default_kind, default_format=default_format)
    return parser


def lookup_csv_for_kind(kind: str, override: Path | None) -> Path:
    if override is not None:
        return override
    if kind == "model":
        return DEFAULT_MODEL_LOOKUP_CSV
    return DEFAULT_WEAPON_LOOKUP_CSV


def export_one_entry(
    entry: LookupExportEntry,
    *,
    work_root: Path,
    mfx_path: Path,
    export_format: str,
    lod: int,
    want_preview: bool,
    want_report: bool,
    engine: str = "native",
) -> EntryRunResult:
    entry_started = time.perf_counter()
    with collect_command_timings() as timings:
        _exports, jobs, failures = export_all_models(
            input_path=entry.archive_path,
            output_root=work_root / entry.safe_serial_name,
            arcs=[entry.archive_path],
            mfx_path=mfx_path,
            export_format=export_format,
            lod=lod,
            want_preview=want_preview,
            want_report=want_report,
            limit=None,
            dry_run=False,
            engine=engine,
        )
    return EntryRunResult(
        entry=entry,
        elapsed_ms=int((time.perf_counter() - entry_started) * 1000),
        timings=list(timings),
        jobs=jobs,
        failures=failures,
    )


def run_parallel_exports(
    *,
    entries: Sequence[LookupExportEntry],
    worker_count: int,
    export_entry: Callable[[LookupExportEntry], EntryRunResult],
    on_complete: Callable[[int, LookupExportEntry, EntryRunResult], None],
    executor_factory: Callable[..., object] = concurrent.futures.ThreadPoolExecutor,
    as_completed_func: Callable[..., Iterable[concurrent.futures.Future]] = concurrent.futures.as_completed,
) -> list[EntryRunResult]:
    print(f"workers={worker_count}", flush=True)
    executor = executor_factory(max_workers=worker_count)
    future_to_entry = {}
    results: list[EntryRunResult] = []
    try:
        for entry in entries:
            if _CANCEL_REQUESTED.is_set():
                raise KeyboardInterrupt
            future_to_entry[executor.submit(export_entry, entry)] = entry

        completed = 0
        for future in as_completed_func(future_to_entry):
            entry = future_to_entry[future]
            result = future.result()
            completed += 1
            on_complete(completed, entry, result)
            results.append(result)
    except KeyboardInterrupt:
        request_cancel_active_processes()
        for future in future_to_entry:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    return results


def run(args: argparse.Namespace) -> ExportRunResult:
    clear_cancel_request()
    run_started = time.perf_counter()
    kind = args.default_kind or args.kind
    export_format = args.default_format or args.format
    if export_format == "both":
        export_format = "fbx"
    engine = getattr(
        args,
        "engine",
        "blender" if getattr(args, "default_format", None) in {"fbx", "both"} else "native",
    )

    archive_root = args.archive_root.resolve()
    output_root = args.output.resolve()
    category_root = output_root / kind
    csv_path = lookup_csv_for_kind(kind, args.lookup_csv).resolve()
    work_root = (args.work_dir.resolve() / kind)

    entries = read_lookup_entries(
        csv_path=csv_path,
        archive_root=archive_root,
        kind=kind,
        serial_filters=args.serial,
        contains=args.contains,
        limit=args.limit,
    )
    if not entries:
        raise ValueError(f"no exportable {kind} archive rows found in {csv_path}")
    if not args.mfx.resolve().exists():
        raise FileNotFoundError(f"MFX file not found: {args.mfx.resolve()}")

    plan = {
        "kind": kind,
        "format": export_format,
        "archive_root": str(archive_root),
        "csv": str(csv_path),
        "output": str(category_root),
        "entry_count": len(entries),
    }
    print(json.dumps(plan, indent=2, default=str))
    if args.verbose:
        print(
            json.dumps(
                {"entries": [asdict(entry) for entry in entries]},
                indent=2,
                default=str,
            )
        )
    elif args.dry_run:
        preview_entries = [
            {
                "output_name": entry.output_name,
                "archive_ref": entry.archive_ref,
                "model_id": entry.model_id,
                "part_type": entry.part_type,
            }
            for entry in entries[:20]
        ]
        print(
            json.dumps(
                {
                    "preview_entries": preview_entries,
                    "preview_count": len(preview_entries),
                    "remaining_count": max(0, len(entries) - len(preview_entries)),
                },
                indent=2,
            )
        )
    if args.dry_run:
        return ExportRunResult(
            entry_count=len(entries),
            model_count=0,
            fbx_job_count=0,
            failure_count=0,
            output_root=output_root,
            category_root=category_root,
            total_elapsed_ms=int((time.perf_counter() - run_started) * 1000),
        )

    all_jobs: list[BlenderJob] = []
    all_failures: list[dict[str, str]] = []
    initialized_outputs: set[str] = set()
    model_count = 0
    worker_count = max(1, args.workers)
    reset_directory(work_root, args.work_dir.resolve())
    if not args.serial and not args.contains:
        reset_directory(category_root, output_root)
    with quiet_tool_output(enabled=not args.verbose):
        def complete_entry(
            index: int,
            entry: LookupExportEntry,
            result: EntryRunResult,
        ) -> None:
            nonlocal model_count
            if result.jobs:
                if engine != "blender":
                    raise ValueError("native export unexpectedly returned Blender jobs")
                print_progress(
                    index,
                    len(entries),
                    entry,
                    "fbx",
                    details=f"{len(result.jobs)} job(s)",
                )
                run_blender_batch(
                    output_root=work_root,
                    blender_path=args.blender.resolve(),
                    jobs=result.jobs,
                    dry_run=False,
                )
            copied = materialize_entry_clean_output(
                category_root, work_root, entry, initialized_outputs
            )
            model_count += copied
            print_progress(
                index,
                len(entries),
                entry,
                "done",
                elapsed_ms=result.elapsed_ms,
                details=summarize_timings(result.timings),
            )
            all_jobs.extend(result.jobs)
            all_failures.extend(result.failures)

        if worker_count == 1:
            for index, entry in enumerate(entries, start=1):
                print_progress(
                    index, len(entries), entry, f"export {export_format}"
                )
                result = export_one_entry(
                    entry,
                    work_root=work_root,
                    mfx_path=args.mfx.resolve(),
                    export_format=export_format,
                    lod=args.lod,
                    want_preview=args.preview,
                    want_report=args.report,
                    engine=engine,
                )
                complete_entry(index, entry, result)
        else:
            def export_entry(entry: LookupExportEntry) -> EntryRunResult:
                return export_one_entry(
                    entry,
                    work_root=work_root,
                    mfx_path=args.mfx.resolve(),
                    export_format=export_format,
                    lod=args.lod,
                    want_preview=args.preview,
                    want_report=args.report,
                    engine=engine,
                )

            def on_complete(
                completed: int,
                entry: LookupExportEntry,
                result: EntryRunResult,
            ) -> None:
                complete_entry(completed, entry, result)

            run_parallel_exports(
                entries=entries,
                worker_count=worker_count,
                export_entry=export_entry,
                on_complete=on_complete,
            )

    return ExportRunResult(
        entry_count=len(entries),
        model_count=model_count,
        fbx_job_count=len(all_jobs),
        failure_count=len(all_failures),
        output_root=output_root,
        category_root=category_root,
        total_elapsed_ms=int((time.perf_counter() - run_started) * 1000),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    default_kind: str | None = None,
    default_format: str | None = None,
) -> int:
    parser = build_parser(default_kind=default_kind, default_format=default_format)
    args = parser.parse_args(argv)
    result = run(args)
    print(json.dumps(asdict(result), indent=2, default=str))
    return 0 if result.failure_count == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        request_cancel_active_processes()
        print("cancelled by user", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
