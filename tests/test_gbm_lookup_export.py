import importlib.util
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_lookup_export.py"
TOOLS_DIR = MODULE_PATH.parent
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

    def test_row_archive_refs_weapon_uses_ch_archives_and_skips_vfx_mot(self) -> None:
        row = {
            "ch_archives": "ch/10100.arc; ch/10100_vfx.arc; ch/10100_mot.arc",
        }

        actual = gbm_lookup_export.row_archive_refs(row, "weapon")

        self.assertEqual(actual, ["ch/10100.arc"])

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
