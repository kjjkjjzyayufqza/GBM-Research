import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _load(module_name: str):
    module_path = TOOLS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gbm_model_mesh = _load("gbm_model_mesh")
gbm_obj_writer = _load("gbm_obj_writer")


def _single_triangle_mesh() -> "gbm_model_mesh.MeshData":
    part = gbm_model_mesh.MeshPart(
        name="cube_mat_0",
        material_index=0,
        positions=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32
        ),
        normals=np.array(
            [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float32
        ),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int32),
        joints=None,
        weights=None,
    )
    material = gbm_model_mesh.MaterialDef(
        index=0, name="mat_0", base_png=None, normal_png=None
    )
    return gbm_model_mesh.MeshData(
        name="cube",
        parts=(part,),
        bones=(),
        materials=(material,),
        space="blender",
    )


class WriteObjBytesTests(unittest.TestCase):
    def test_obj_writer_emits_one_vertex_uv_normal_per_part_vertex(self) -> None:
        mesh = _single_triangle_mesh()

        obj_bytes, _ = gbm_obj_writer.write_obj_bytes(mesh)
        text = obj_bytes.decode("utf-8")
        lines = text.splitlines()

        self.assertEqual(sum(1 for line in lines if line.startswith("v ")), 3)
        self.assertEqual(sum(1 for line in lines if line.startswith("vt ")), 3)
        self.assertEqual(sum(1 for line in lines if line.startswith("vn ")), 3)
        self.assertEqual(sum(1 for line in lines if line.startswith("f ")), 1)
        self.assertTrue(any(line.startswith("o cube_mat_0") for line in lines))

    def test_obj_writer_face_indices_are_one_based_and_reference_part_vertices(self) -> None:
        mesh = _single_triangle_mesh()

        obj_bytes, _ = gbm_obj_writer.write_obj_bytes(mesh)
        face_line = next(
            line
            for line in obj_bytes.decode("utf-8").splitlines()
            if line.startswith("f ")
        )

        self.assertEqual(face_line, "f 1/1/1 2/2/2 3/3/3")

    def test_obj_writer_emits_objects_materials_and_texture_maps(self) -> None:
        first = _single_triangle_mesh().parts[0]
        second = gbm_model_mesh.MeshPart(
            name="cube_mat_1",
            material_index=1,
            positions=first.positions.copy(),
            normals=first.normals.copy(),
            uvs=first.uvs.copy(),
            triangles=first.triangles.copy(),
            joints=None,
            weights=None,
        )
        mesh = gbm_model_mesh.MeshData(
            name="cube",
            parts=(first, second),
            bones=(),
            materials=(
                gbm_model_mesh.MaterialDef(
                    index=0,
                    name="mat_0",
                    base_png=Path("textures/base0.png"),
                    normal_png=Path("textures/normal0.png"),
                ),
                gbm_model_mesh.MaterialDef(
                    index=1,
                    name="mat_1",
                    base_png=Path("textures/base1.png"),
                    normal_png=None,
                ),
            ),
            space="blender",
        )

        obj_bytes, mtl_bytes = gbm_obj_writer.write_obj_bytes(mesh)
        obj = obj_bytes.decode("utf-8")
        mtl = mtl_bytes.decode("utf-8")

        self.assertIn("\no cube_mat_0\nusemtl mat_0\n", obj)
        self.assertIn("\no cube_mat_1\nusemtl mat_1\n", obj)
        self.assertIn("f 4/4/4 5/5/5 6/6/6", obj)
        self.assertIn("newmtl mat_0", mtl)
        self.assertIn("map_Kd textures/base0.png", mtl)
        self.assertIn("map_Bump textures/normal0.png", mtl)
        self.assertIn("newmtl mat_1", mtl)
        self.assertIn("map_Kd textures/base1.png", mtl)


if __name__ == "__main__":
    unittest.main()
