import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_batch.py"
SPEC = importlib.util.spec_from_file_location("gbm_batch", MODULE_PATH)
gbm_batch = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_batch
SPEC.loader.exec_module(gbm_batch)


class BatchOutputPathTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
