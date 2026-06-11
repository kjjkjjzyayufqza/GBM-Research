import importlib.util
import sys
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_start.py"
SPEC = importlib.util.spec_from_file_location("gbm_start", MODULE_PATH)
gbm_start = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_start
SPEC.loader.exec_module(gbm_start)


class SelectModPathsTests(unittest.TestCase):
    def test_entry_output_paths_returns_empty_list_without_entries(self) -> None:
        self.assertEqual(gbm_start.entry_output_paths({}), [])
        self.assertEqual(gbm_start.entry_output_paths({"entries": "bad"}), [])

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


class RunCommandTests(unittest.TestCase):
    def test_run_command_kills_child_process_on_keyboard_interrupt(self) -> None:
        class FakeProcess:
            def __init__(self, *_args, **_kwargs) -> None:
                self.returncode = None
                self.killed = False
                fake_processes.append(self)

            def wait(self) -> int:
                raise KeyboardInterrupt

            def kill(self) -> None:
                self.killed = True

        fake_processes: list[FakeProcess] = []

        with mock.patch.object(gbm_start.subprocess, "Popen", FakeProcess):
            with self.assertRaises(KeyboardInterrupt):
                gbm_start.run_command(["fake-tool"], dry_run=False)

        self.assertEqual(len(fake_processes), 1)
        self.assertTrue(fake_processes[0].killed)


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


class TextureSourceDirsTests(unittest.TestCase):
    def test_includes_sibling_texture_dirs_without_mod_files(self) -> None:
        root = Path("E:/tmp/out/extracted")
        exported_mod = root / "character" / "chr106009" / "mod" / "chr106003_01.mod"
        sibling_tex = root / "character" / "chr211112" / "mod" / "chr211112_P00_BM.tex"

        with mock.patch.object(Path, "rglob", return_value=[sibling_tex]):
            actual = gbm_start.texture_source_dirs([exported_mod], root)

        self.assertEqual(
            actual,
            [
                root / "character" / "chr106009" / "mod",
                root / "character" / "chr211112" / "mod",
            ],
        )


if __name__ == "__main__":
    unittest.main()
