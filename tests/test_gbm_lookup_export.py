import importlib.util
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_lookup_export.py"
TOOLS_DIR = MODULE_PATH.parent
WORKSPACE_ROOT = MODULE_PATH.parents[2]
REAL_ARCHIVE_ROOT = (
    WORKSPACE_ROOT / "com.bandainamcoent.gb_jp" / "files" / "dlc" / "archive"
)
REAL_WEAPON_CSV = TOOLS_DIR / "gbm_weapon_parts_index.csv"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
SPEC = importlib.util.spec_from_file_location("gbm_lookup_export", MODULE_PATH)
gbm_lookup_export = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_lookup_export
SPEC.loader.exec_module(gbm_lookup_export)


class LookupExportTests(unittest.TestCase):
    def test_parser_defaults_to_one_worker(self) -> None:
        parser = gbm_lookup_export.build_parser(default_kind="model")

        args = parser.parse_args(["--format", "obj", "E:/archive"])

        self.assertEqual(args.workers, 1)

    def test_sanitize_path_component_removes_windows_and_extra_punctuation(self) -> None:
        actual = gbm_lookup_export.sanitize_path_component('RX:78/[!] "Test".')

        self.assertEqual(actual, "RX_78_Test")

    def test_row_archive_refs_model_uses_primary_and_skips_vfx_mot(self) -> None:
        row = {
            "primary_ch_archive": "ch/10000.arc",
            "ch_archives": "ch/10000.arc; ch/10000_vfx.arc; ch/10000_mot.arc",
        }

        actual = gbm_lookup_export.row_archive_refs(row, "model")

        self.assertEqual(actual, ["ch/10000.arc"])

    def test_row_archive_refs_weapon_uses_ch_archives_for_mesh_export(self) -> None:
        row = {
            "parts_id": "31000001",
            "ch_archives": "ch/10100.arc; ch/10100_vfx.arc",
            "we_archives": "we/31000001.arc",
        }

        actual = gbm_lookup_export.row_archive_refs(row, "weapon")

        self.assertEqual(actual, ["ch/10100.arc"])

    def test_row_archive_refs_weapon_skips_rows_without_ch_archive(self) -> None:
        row = {
            "parts_id": "31000001",
            "ch_archives": "",
            "we_archives": "we/31000001.arc",
        }

        actual = gbm_lookup_export.row_archive_refs(row, "weapon")

        self.assertEqual(actual, [])

    def test_row_archive_refs_weapon_ignores_we_only_rows(self) -> None:
        row = {
            "parts_id": "31003603",
            "has_ch_archive": "no",
            "ch_archives": "",
            "has_we_archive": "yes",
            "we_archives": "we/31003603.arc",
        }

        actual = gbm_lookup_export.row_archive_refs(row, "weapon")

        self.assertEqual(actual, [])

    @unittest.skipUnless(
        REAL_ARCHIVE_ROOT.joinpath("ch", "10100.arc").is_file(),
        "requires local game archive at com.bandainamcoent.gb_jp/files/dlc/archive",
    )
    def test_read_weapon_entries_from_real_csv_uses_ch_archives(self) -> None:
        entries = gbm_lookup_export.read_lookup_entries(
            csv_path=REAL_WEAPON_CSV,
            archive_root=REAL_ARCHIVE_ROOT,
            kind="weapon",
            serial_filters=["RX-78-2"],
            limit=3,
        )

        self.assertGreater(len(entries), 0)
        for entry in entries:
            self.assertTrue(
                entry.archive_ref.startswith("ch/"),
                f"expected ch archive, got {entry.archive_ref}",
            )
            self.assertTrue(entry.archive_path.is_file(), entry.archive_path)

    @unittest.skipUnless(
        REAL_ARCHIVE_ROOT.joinpath("we", "31001402.arc").is_file(),
        "requires local game archive at com.bandainamcoent.gb_jp/files/dlc/archive",
    )
    def test_read_weapon_entries_without_ch_archive_are_skipped(self) -> None:
        entries = gbm_lookup_export.read_lookup_entries(
            csv_path=REAL_WEAPON_CSV,
            archive_root=REAL_ARCHIVE_ROOT,
            kind="weapon",
            serial_filters=["MS-06"],
            limit=10,
        )

        self.assertFalse(any(entry.archive_ref == "we/31001402.arc" for entry in entries))

    def test_read_lookup_entries_dedupes_serial_archive_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_root = root / "archive"
            ch_dir = archive_root / "ch"
            ch_dir.mkdir(parents=True)
            (ch_dir / "10000.arc").write_bytes(b"ARCC")
            csv_path = root / "lookup.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "serial_name,model_id,primary_ch_archive,ch_archives",
                        "RX-78-2,10000,ch/10000.arc,ch/10000.arc; ch/10000_vfx.arc",
                        "RX-78-2,10000,ch/10000.arc,ch/10000.arc",
                    ]
                ),
                encoding="utf-8",
            )

            actual = gbm_lookup_export.read_lookup_entries(
                csv_path=csv_path,
                archive_root=archive_root,
                kind="model",
            )

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].safe_serial_name, "RX-78-2")
        self.assertEqual(actual[0].output_name, "RX-78-2")
        self.assertEqual(actual[0].archive_ref, "ch/10000.arc")

    def test_read_lookup_entries_suffixes_duplicate_serial_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_root = root / "archive"
            ch_dir = archive_root / "ch"
            ch_dir.mkdir(parents=True)
            (ch_dir / "10000.arc").write_bytes(b"ARCC")
            (ch_dir / "90000.arc").write_bytes(b"ARCC")
            csv_path = root / "lookup.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "serial_name,model_id,primary_ch_archive,ch_archives",
                        "RX-78-2,10000,ch/10000.arc,ch/10000.arc",
                        "RX-78-2,90000,ch/90000.arc,ch/90000.arc",
                    ]
                ),
                encoding="utf-8",
            )

            actual = gbm_lookup_export.read_lookup_entries(
                csv_path=csv_path,
                archive_root=archive_root,
                kind="model",
            )

        self.assertEqual([entry.output_name for entry in actual], ["RX-78-2", "RX-78-2_1"])

    def test_read_lookup_entries_without_serial_filter_reads_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_root = root / "archive"
            ch_dir = archive_root / "ch"
            ch_dir.mkdir(parents=True)
            (ch_dir / "10000.arc").write_bytes(b"ARCC")
            (ch_dir / "10004.arc").write_bytes(b"ARCC")
            csv_path = root / "lookup.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "serial_name,model_id,primary_ch_archive,ch_archives",
                        "RX-78-2,10000,ch/10000.arc,ch/10000.arc",
                        "RX-78NT-1,10004,ch/10004.arc,ch/10004.arc",
                    ]
                ),
                encoding="utf-8",
            )

            actual = gbm_lookup_export.read_lookup_entries(
                csv_path=csv_path,
                archive_root=archive_root,
                kind="model",
            )

        self.assertEqual([entry.serial_name for entry in actual], ["RX-78-2", "RX-78NT-1"])

    def test_copy_allowed_tree_skips_manifests_and_raw_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            (source / "obj").mkdir(parents=True)
            (source / "obj" / "model.obj").write_text("obj", encoding="utf-8")
            (source / "obj" / "model.mtl").write_text("mtl", encoding="utf-8")
            (source / "obj" / "model_obj_manifest.json").write_text(
                "{}", encoding="utf-8"
            )
            (source / "raw.mod").write_bytes(b"MOD\0")
            (source / "fbx").mkdir()
            (source / "fbx" / "model.fbx").write_bytes(b"fbx")
            (source / "fbx" / "model_BM.png").write_bytes(b"png")

            copied = gbm_lookup_export.copy_allowed_tree(source, destination)

            copied_files = sorted(
                path.relative_to(destination).as_posix()
                for path in destination.rglob("*")
                if path.is_file()
            )

        self.assertEqual(copied, 4)
        self.assertEqual(
            copied_files,
            [
                "fbx/model.fbx",
                "fbx/model_BM.png",
                "obj/model.mtl",
                "obj/model.obj",
            ],
        )

    def test_run_materializes_each_sequential_entry_before_starting_next_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            work_dir = root / "work"
            archive_root = root / "archive"
            mfx_path = root / "ShaderPackage.mfx"
            mfx_path.write_bytes(b"MFX")
            first_archive = archive_root / "ch" / "10300.arc"
            second_archive = archive_root / "ch" / "10301.arc"
            first_archive.parent.mkdir(parents=True)
            first_archive.write_bytes(b"ARCC")
            second_archive.write_bytes(b"ARCC")
            entries = [
                gbm_lookup_export.LookupExportEntry(
                    serial_name="RX-79(G)-1",
                    safe_serial_name="RX-79_G_1",
                    output_name="RX-79_G_1",
                    archive_ref="ch/10300.arc",
                    archive_path=first_archive,
                    row_index=2,
                    model_id="10300",
                    part_type="weapon",
                ),
                gbm_lookup_export.LookupExportEntry(
                    serial_name="RX-79(G)-2",
                    safe_serial_name="RX-79_G_2",
                    output_name="RX-79_G_2",
                    archive_ref="ch/10301.arc",
                    archive_path=second_archive,
                    row_index=3,
                    model_id="10301",
                    part_type="weapon",
                ),
            ]
            first_final_obj = (
                output_root
                / "weapon"
                / "RX-79_G_1"
                / "ma10300"
                / "obj"
                / "ma10300.obj"
            )
            calls = 0

            def fake_export_one_entry(entry, *, work_root, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    self.assertTrue(first_final_obj.exists())
                model_stem = f"ma{entry.archive_path.stem}"
                model_root = (
                    work_root
                    / entry.safe_serial_name
                    / entry.archive_path.stem
                    / "models"
                    / model_stem
                    / "obj"
                )
                model_root.mkdir(parents=True)
                (model_root / f"{model_stem}.obj").write_text("obj", encoding="utf-8")
                return gbm_lookup_export.EntryRunResult(
                    entry=entry,
                    elapsed_ms=1,
                    timings=[],
                    jobs=[],
                    failures=[],
                )

            args = Namespace(
                default_kind="weapon",
                kind=None,
                default_format="obj",
                format=None,
                archive_root=archive_root,
                output=output_root,
                lookup_csv=None,
                work_dir=work_dir,
                workers=1,
                mfx=mfx_path,
                blender=root / "blender.exe",
                lod=0,
                preview=False,
                report=False,
                serial=[],
                contains=False,
                limit=None,
                dry_run=False,
                verbose=False,
            )

            with mock.patch.object(
                gbm_lookup_export, "read_lookup_entries", return_value=entries
            ), mock.patch.object(
                gbm_lookup_export, "export_one_entry", side_effect=fake_export_one_entry
            ):
                result = gbm_lookup_export.run(args)

            self.assertEqual(result.model_count, 2)
            self.assertEqual(calls, 2)
            self.assertTrue(first_final_obj.exists())

    def test_run_materializes_fbx_entry_after_entry_blender_jobs_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            work_dir = root / "work"
            archive_root = root / "archive"
            mfx_path = root / "ShaderPackage.mfx"
            blender_path = root / "blender.exe"
            mfx_path.write_bytes(b"MFX")
            blender_path.write_bytes(b"BLENDER")
            first_archive = archive_root / "ch" / "10300.arc"
            second_archive = archive_root / "ch" / "10301.arc"
            first_archive.parent.mkdir(parents=True)
            first_archive.write_bytes(b"ARCC")
            second_archive.write_bytes(b"ARCC")
            entries = [
                gbm_lookup_export.LookupExportEntry(
                    serial_name="RX-79(G)-1",
                    safe_serial_name="RX-79_G_1",
                    output_name="RX-79_G_1",
                    archive_ref="ch/10300.arc",
                    archive_path=first_archive,
                    row_index=2,
                    model_id="10300",
                    part_type="weapon",
                ),
                gbm_lookup_export.LookupExportEntry(
                    serial_name="RX-79(G)-2",
                    safe_serial_name="RX-79_G_2",
                    output_name="RX-79_G_2",
                    archive_ref="ch/10301.arc",
                    archive_path=second_archive,
                    row_index=3,
                    model_id="10301",
                    part_type="weapon",
                ),
            ]
            first_final_fbx = (
                output_root
                / "weapon"
                / "RX-79_G_1"
                / "ma10300"
                / "fbx"
                / "ma10300.fbx"
            )
            calls = 0

            def fake_export_one_entry(entry, *, work_root, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    self.assertTrue(first_final_fbx.exists())
                model_stem = f"ma{entry.archive_path.stem}"
                model_root = (
                    work_root
                    / entry.safe_serial_name
                    / entry.archive_path.stem
                    / "models"
                    / model_stem
                )
                obj_dir = model_root / "obj"
                obj_dir.mkdir(parents=True)
                (obj_dir / f"{model_stem}.obj").write_text("obj", encoding="utf-8")
                job = gbm_lookup_export.BlenderJob(
                    input_obj=obj_dir / f"{model_stem}.obj",
                    output_fbx=model_root / "fbx" / f"{model_stem}.fbx",
                    lod=0,
                )
                return gbm_lookup_export.EntryRunResult(
                    entry=entry,
                    elapsed_ms=1,
                    timings=[],
                    jobs=[job],
                    failures=[],
                )

            def fake_run_blender_batch(*, jobs, **_kwargs):
                for job in jobs:
                    job.output_fbx.parent.mkdir(parents=True)
                    job.output_fbx.write_bytes(b"fbx")

            args = Namespace(
                default_kind="weapon",
                kind=None,
                default_format="fbx",
                format=None,
                archive_root=archive_root,
                output=output_root,
                lookup_csv=None,
                work_dir=work_dir,
                workers=1,
                mfx=mfx_path,
                blender=blender_path,
                lod=0,
                preview=False,
                report=False,
                serial=[],
                contains=False,
                limit=None,
                dry_run=False,
                verbose=False,
            )

            with mock.patch.object(
                gbm_lookup_export, "read_lookup_entries", return_value=entries
            ), mock.patch.object(
                gbm_lookup_export, "export_one_entry", side_effect=fake_export_one_entry
            ), mock.patch.object(
                gbm_lookup_export, "run_blender_batch", side_effect=fake_run_blender_batch
            ):
                result = gbm_lookup_export.run(args)

            self.assertEqual(result.model_count, 2)
            self.assertEqual(result.fbx_job_count, 2)
            self.assertEqual(calls, 2)
            self.assertTrue(first_final_fbx.exists())

    def test_parallel_export_cancels_futures_without_waiting_on_keyboard_interrupt(self) -> None:
        class FakeFuture:
            def __init__(self) -> None:
                self.cancelled = False

            def cancel(self) -> bool:
                self.cancelled = True
                return True

        class FakeExecutor:
            def __init__(self, max_workers: int) -> None:
                self.max_workers = max_workers
                self.futures: list[FakeFuture] = []
                self.shutdown_calls: list[dict[str, bool]] = []

            def submit(self, _func, _entry) -> FakeFuture:
                future = FakeFuture()
                self.futures.append(future)
                return future

            def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
                self.shutdown_calls.append(
                    {"wait": wait, "cancel_futures": cancel_futures}
                )

        created_executors: list[FakeExecutor] = []

        def executor_factory(max_workers: int) -> FakeExecutor:
            executor = FakeExecutor(max_workers)
            created_executors.append(executor)
            return executor

        def interrupted_as_completed(_futures):
            raise KeyboardInterrupt

        entries = [
            mock.Mock(spec=gbm_lookup_export.LookupExportEntry),
            mock.Mock(spec=gbm_lookup_export.LookupExportEntry),
        ]

        with mock.patch.object(
            gbm_lookup_export, "request_cancel_active_processes"
        ) as request_cancel:
            with self.assertRaises(KeyboardInterrupt):
                gbm_lookup_export.run_parallel_exports(
                    entries=entries,
                    worker_count=3,
                    export_entry=lambda entry: entry,
                    on_complete=lambda _completed, _entry, _result: None,
                    executor_factory=executor_factory,
                    as_completed_func=interrupted_as_completed,
                )

        executor = created_executors[0]
        self.assertEqual(executor.max_workers, 3)
        self.assertEqual(
            executor.shutdown_calls, [{"wait": False, "cancel_futures": True}]
        )
        self.assertTrue(all(future.cancelled for future in executor.futures))
        request_cancel.assert_called_once_with()

    def test_quiet_run_command_kills_child_process_on_keyboard_interrupt(self) -> None:
        class FakeProcess:
            def __init__(self, *_args, **_kwargs) -> None:
                self.returncode = None
                self.killed = False
                fake_processes.append(self)

            def communicate(self) -> tuple[str, str]:
                raise KeyboardInterrupt

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout: float | None = None) -> int:
                self.returncode = -9
                return self.returncode

        fake_processes: list[FakeProcess] = []

        with mock.patch.object(gbm_lookup_export.subprocess, "Popen", FakeProcess):
            with self.assertRaises(KeyboardInterrupt):
                gbm_lookup_export.quiet_run_command(["fake-tool"], dry_run=False)

        self.assertEqual(len(fake_processes), 1)
        self.assertTrue(fake_processes[0].killed)


if __name__ == "__main__":
    unittest.main()
