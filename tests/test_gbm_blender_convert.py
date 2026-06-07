import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path(
    os.environ.get(
        "GBM_BLENDER",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    )
)
CONVERTER = REPO_ROOT / "tools" / "gbm_blender_convert.py"


def run_blender(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout + completed.stderr


def extract_json_marker(output: str, marker: str) -> object:
    for line in output.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError(f"marker {marker!r} not found in Blender output:\n{output}")


class BlenderConvertIntegrationTests(unittest.TestCase):
    def test_exported_fbx_has_no_helper_root_empty(self) -> None:
        self.assertTrue(BLENDER.exists(), f"Blender not found at {BLENDER}")

        with tempfile.TemporaryDirectory() as temp_directory:
            temp_dir = Path(temp_directory)
            input_obj = temp_dir / "probe.obj"
            output_fbx = temp_dir / "probe.fbx"
            report = temp_dir / "probe_report.json"
            input_obj.write_text(
                "# axis_mode: engine\n"
                "v 0 0 0\n"
                "v 1 0 0\n"
                "v 0 1 0\n"
                "f 1 2 3\n",
                encoding="utf-8",
            )

            run_blender(
                [
                    str(BLENDER),
                    "--background",
                    "--python",
                    str(CONVERTER),
                    "--",
                    "--input-obj",
                    str(input_obj),
                    "--output-fbx",
                    str(output_fbx),
                    "--report",
                    str(report),
                ]
            )
            report_data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(
                report_data["fbx_export_settings"],
                {
                    "use_space_transform": True,
                    "bake_space_transform": False,
                    "axis_forward": "Z",
                    "axis_up": "Y",
                    "primary_bone_axis": "-X",
                    "secondary_bone_axis": "Y",
                },
            )
            self.assertEqual(report_data["fbx_roundtrip"]["helper_root_empties"], [])

            inspect_expr = (
                "import bpy, json;"
                "bpy.ops.object.select_all(action='SELECT');"
                "bpy.ops.object.delete(use_global=False);"
                f"bpy.ops.import_scene.fbx(filepath=r'{output_fbx}');"
                "payload=[{'name': obj.name, 'type': obj.type, "
                "'parent': obj.parent.name if obj.parent else None}"
                " for obj in bpy.context.scene.objects if obj.type in {'EMPTY','MESH','ARMATURE'}];"
                "print('GBM_TEST_OBJECTS=' + json.dumps(payload))"
            )
            inspect_output = run_blender(
                [
                    str(BLENDER),
                    "--background",
                    "--python-expr",
                    inspect_expr,
                ]
            )
            objects = extract_json_marker(inspect_output, "GBM_TEST_OBJECTS=")

            self.assertFalse(
                any(
                    obj["type"] == "EMPTY" and obj["name"].endswith("_export_root")
                    for obj in objects
                ),
                objects,
            )


if __name__ == "__main__":
    unittest.main()
