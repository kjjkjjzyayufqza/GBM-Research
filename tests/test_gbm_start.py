import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_start.py"
SPEC = importlib.util.spec_from_file_location("gbm_start", MODULE_PATH)
gbm_start = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_start
SPEC.loader.exec_module(gbm_start)


class SelectModPathsTests(unittest.TestCase):
    def test_without_model_stem_returns_all_sorted_mods(self) -> None:
        extracted_dir = Path("E:/tmp/out/extracted")
        manifest = {
            "entries": [
                {"output": str(extracted_dir / "character" / "chr122352" / "mod" / "chr122352.mod")},
                {"output": str(extracted_dir / "character" / "chr122350" / "mod" / "chr122350.mod")},
                {"output": str(extracted_dir / "character" / "chr122351" / "mod" / "chr122351.mod")},
            ]
        }

        actual = gbm_start.select_mod_paths(manifest, extracted_dir, model_stem=None)

        self.assertEqual(
            actual,
            [
                extracted_dir / "character" / "chr122350" / "mod" / "chr122350.mod",
                extracted_dir / "character" / "chr122351" / "mod" / "chr122351.mod",
                extracted_dir / "character" / "chr122352" / "mod" / "chr122352.mod",
            ],
        )

    def test_with_model_stem_returns_only_matching_mod(self) -> None:
        extracted_dir = Path("E:/tmp/out/extracted")
        manifest = {
            "entries": [
                {"output": str(extracted_dir / "character" / "chr122352" / "mod" / "chr122352.mod")},
                {"output": str(extracted_dir / "character" / "chr122350" / "mod" / "chr122350.mod")},
            ]
        }

        actual = gbm_start.select_mod_paths(
            manifest, extracted_dir, model_stem="chr122350"
        )

        self.assertEqual(
            actual,
            [extracted_dir / "character" / "chr122350" / "mod" / "chr122350.mod"],
        )

    def test_with_duplicate_model_stem_raises_ambiguity_error(self) -> None:
        extracted_dir = Path("E:/tmp/out/extracted")
        manifest = {
            "entries": [
                {"output": str(extracted_dir / "character" / "shared" / "mod" / "shared.mod")},
                {"output": str(extracted_dir / "equip" / "shared" / "mod" / "shared.mod")},
            ]
        }

        with self.assertRaises(FileNotFoundError) as context:
            gbm_start.select_mod_paths(manifest, extracted_dir, model_stem="shared")

        self.assertIn("Multiple .mod files match", str(context.exception))


class BlenderJobRecordTests(unittest.TestCase):
    def test_record_serializes_optional_fields_as_null(self) -> None:
        job = gbm_start.BlenderJob(
            input_obj=Path("E:/out/model/obj/model.obj"),
            output_fbx=Path("E:/out/model/fbx/model.fbx"),
            texture=Path("E:/out/model/png/model_BM.png"),
            normal_texture=None,
            mod=Path("E:/out/model/extracted/model.mod"),
            mfx=Path("E:/tools/ShaderPackage.mfx"),
            lod=1,
            preview=None,
            report=None,
        )

        actual = gbm_start.blender_job_record(job)

        self.assertEqual(actual["normal_texture"], None)
        self.assertEqual(actual["preview"], None)
        self.assertEqual(actual["report"], None)
        self.assertEqual(actual["lod"], 1)
        self.assertEqual(actual["input_obj"], "E:\\out\\model\\obj\\model.obj")


class UniqueModelDirectoryNameTests(unittest.TestCase):
    def test_duplicate_stems_get_numbered_suffixes(self) -> None:
        mod_paths = [
            Path("E:/tmp/out/extracted/character/shared/mod/shared.mod"),
            Path("E:/tmp/out/extracted/equip/shared/mod/shared.mod"),
            Path("E:/tmp/out/extracted/character/unique/mod/unique.mod"),
        ]

        actual = gbm_start.unique_model_directory_names(mod_paths)

        self.assertEqual(
            actual,
            {
                mod_paths[0]: "shared",
                mod_paths[1]: "shared__2",
                mod_paths[2]: "unique",
            },
        )


if __name__ == "__main__":
    unittest.main()
