import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_blender_addon_core.py"
TOOLS_DIR = MODULE_PATH.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
SPEC = importlib.util.spec_from_file_location("gbm_blender_addon_core", MODULE_PATH)
gbm_blender_addon_core = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_blender_addon_core
SPEC.loader.exec_module(gbm_blender_addon_core)


class BlenderAddonCoreTests(unittest.TestCase):
    def test_require_directory_rejects_blank_output_folder(self) -> None:
        with self.assertRaises(ValueError):
            gbm_blender_addon_core.require_directory("", "Output folder")

    def test_export_path_uses_safe_name_and_format_extension(self) -> None:
        path = gbm_blender_addon_core.export_path(
            Path("E:/out"),
            "RX:78/[Test]",
            "glb",
        )

        self.assertEqual(path, Path("E:/out/RX_78__Test.glb"))

    def test_iter_unique_paths_dedupes_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "ch" / "210100.arc"
            second = root / "ch" / "210100.arc"
            first.parent.mkdir()
            first.write_bytes(b"ARCC")

            actual = gbm_blender_addon_core.iter_unique_paths([first, second])

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].name, "210100.arc")

    def test_unknown_export_format_fails_before_writing(self) -> None:
        with self.assertRaises(ValueError):
            gbm_blender_addon_core.export_extension("dae")

    def test_resolve_mfx_path_falls_back_from_stale_addon_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "ShaderPackage.mfx"
            bundled.write_bytes(b"MFX")
            stale = (
                Path("C:/Users/example/AppData/Roaming/Blender Foundation")
                / "Blender/4.2/scripts/addons/gbm_arc_tools/ShaderPackage.mfx"
            )

            original_tools_dir = gbm_blender_addon_core.TOOLS_DIR
            gbm_blender_addon_core.TOOLS_DIR = root
            try:
                resolved = gbm_blender_addon_core.resolve_mfx_path(str(stale))
            finally:
                gbm_blender_addon_core.TOOLS_DIR = original_tools_dir

        self.assertEqual(resolved, bundled.resolve())

    @unittest.skipUnless(
        (
            gbm_blender_addon_core.DEFAULT_ARCHIVE_ROOT
            / "ch"
            / "210100.arc"
        ).is_file(),
        "requires local game archive at com.bandainamcoent.gb_jp/files/dlc/archive",
    )
    def test_resolve_lookup_arcs_finds_real_weapon_serial(self) -> None:
        arcs = gbm_blender_addon_core.resolve_lookup_arcs(
            kind="weapon",
            serial="RX-78-2",
            archive_root=gbm_blender_addon_core.DEFAULT_ARCHIVE_ROOT,
            limit=1,
        )

        self.assertEqual(arcs[0].name, "210100.arc")


if __name__ == "__main__":
    unittest.main()
