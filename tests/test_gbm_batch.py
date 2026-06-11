import importlib.util
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_batch.py"
SPEC = importlib.util.spec_from_file_location("gbm_batch", MODULE_PATH)
gbm_batch = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_batch
SPEC.loader.exec_module(gbm_batch)


class BatchOutputPathTests(unittest.TestCase):
    def test_single_input_default_output_uses_input_stem(self) -> None:
        input_paths = [Path("E:/game/archive/ch/320900.arc")]

        actual = gbm_batch.resolve_output_root(input_paths, None)

        self.assertEqual(actual, gbm_batch.DEFAULT_OUTPUT_ROOT / "320900")

    def test_multiple_inputs_default_output_uses_shared_batch_root(self) -> None:
        input_paths = [
            Path("E:/game/archive/ch/320900.arc"),
            Path("E:/game/archive/ch/320901.arc"),
        ]

        actual = gbm_batch.resolve_output_root(input_paths, None)

        self.assertEqual(actual, gbm_batch.DEFAULT_OUTPUT_ROOT)

    def test_directory_input_preserves_relative_folder_and_arc_stem(self) -> None:
        input_root = Path("E:/game/archive/ma")
        output_root = Path("E:/out/ma_batch")
        arc_path = input_root / "m800" / "m810a05_night.arc"

        actual = gbm_batch.arc_output_root(input_root, output_root, arc_path)

        self.assertEqual(actual, output_root / "m800" / "m810a05_night")

    def test_file_input_uses_arc_stem_under_output_root(self) -> None:
        arc_path = Path("E:/game/archive/ch/320900.arc")
        output_root = Path("E:/out/single")

        actual = gbm_batch.arc_output_root(arc_path, output_root, arc_path)

        self.assertEqual(actual, output_root / "320900")


class ExportAllModelsTests(unittest.TestCase):
    def test_archive_without_mod_is_skipped_without_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc_path = root / "archive" / "we" / "31000001.arc"
            output_root = root / "out"

            with mock.patch.object(gbm_batch, "run_command"), mock.patch.object(
                gbm_batch,
                "select_mod_paths",
                side_effect=FileNotFoundError("No .mod file found"),
            ):
                exports, jobs, failures = gbm_batch.export_all_models(
                    input_path=arc_path,
                    output_root=output_root,
                    arcs=[arc_path],
                    mfx_path=root / "ShaderPackage.mfx",
                    export_format="obj",
                    lod=0,
                    want_preview=False,
                    want_report=False,
                    limit=None,
                    dry_run=False,
                )

        self.assertEqual(exports, [])
        self.assertEqual(jobs, [])
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
