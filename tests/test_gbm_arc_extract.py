import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_arc_extract.py"
SPEC = importlib.util.spec_from_file_location("gbm_arc_extract", MODULE_PATH)
gbm_arc_extract = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_arc_extract
SPEC.loader.exec_module(gbm_arc_extract)

START_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_start.py"
START_SPEC = importlib.util.spec_from_file_location("gbm_start", START_PATH)
gbm_start = importlib.util.module_from_spec(START_SPEC)
assert START_SPEC.loader is not None
sys.modules[START_SPEC.name] = gbm_start
START_SPEC.loader.exec_module(gbm_start)


def entry(name: str) -> gbm_arc_extract.ArcEntry:
    return gbm_arc_extract.ArcEntry(
        index=0,
        name=name,
        type_code=0,
        compressed_size=0,
        size_flags=0,
        uncompressed_size=0,
        offset=0,
        compressed=False,
    )


class ModelAssetEntryTests(unittest.TestCase):
    def test_accepts_character_mod_resources(self) -> None:
        self.assertTrue(
            gbm_arc_extract.is_model_asset_entry(
                entry("character\\ma302000\\mod\\ma302000.mod")
            )
        )
        self.assertTrue(
            gbm_arc_extract.is_model_asset_entry(
                entry("equip\\shared\\mod\\shared.tex")
            )
        )

    def test_rejects_motion_sound_vfx_and_shell(self) -> None:
        rejected = [
            "motion\\ma\\ma302000\\ma302000.lmt",
            "Sound\\se\\ma_pg\\ma_302000\\wav\\shot.wav",
            "sound\\se\\ma_pg\\ma_302000\\wav\\shot.wav",
            "shell\\ma\\ma302000\\beam.bmb",
            "vfx\\bmb\\ma\\ma302000\\beam\\shot.bmb",
            "vfx\\texture\\ef_t_white_BM.tex",
        ]
        for name in rejected:
            with self.subTest(name=name):
                self.assertFalse(gbm_arc_extract.is_model_asset_entry(entry(name)))

    def test_select_entries_applies_model_assets_only_filter(self) -> None:
        entries = [
            entry("character\\ma302000\\mod\\ma302000.mod"),
            entry("motion\\ma\\ma302000\\ma302000.lmt"),
            entry("vfx\\texture\\ef_t_white_BM.tex"),
        ]

        actual = gbm_arc_extract.select_entries(entries, limit=None, model_assets_only=True)

        self.assertEqual([item.name for item in actual], [entries[0].name])


class ArcExtractCommandTests(unittest.TestCase):
    def test_model_assets_only_adds_cli_flag(self) -> None:
        command = gbm_start.arc_extract_command(
            Path("E:/game/302000.arc"),
            Path("E:/out/extracted"),
            Path("E:/out/extracted/_manifest.json"),
            model_assets_only=True,
        )

        self.assertIn("--model-assets-only", command)

    def test_write_manifest_false_uses_no_manifest_flag(self) -> None:
        command = gbm_start.arc_extract_command(
            Path("E:/game/302000.arc"),
            Path("E:/out/extracted"),
            write_manifest=False,
            model_assets_only=True,
        )

        self.assertIn("--no-manifest", command)
        self.assertNotIn("--manifest", command)


if __name__ == "__main__":
    unittest.main()
