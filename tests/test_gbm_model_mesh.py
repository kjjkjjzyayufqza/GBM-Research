import importlib.util
import struct
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
gbm_mod_obj_probe = _load("gbm_mod_obj_probe")
gbm_mfx_inspect = _load("gbm_mfx_inspect")


def _element(format_id: int, component_count: int, byte_offset: int = 0):
    sizes = {1: 4, 2: 2, 5: 2, 8: 1, 9: 1, 10: 1}
    return gbm_mfx_inspect.InputElement(
        semantic="Test",
        semantic_index=0,
        format_id=format_id,
        format_name=str(format_id),
        component_count=component_count,
        byte_offset=byte_offset,
        byte_size=sizes[format_id] * component_count,
        packed=0,
    )


def _pack(format_id: int, values) -> bytes:
    if format_id == 1:
        return struct.pack(f"<{len(values)}f", *values)
    if format_id in (2, 5):
        return struct.pack(f"<{len(values)}h", *values)
    if format_id == 8:
        return bytes(values)
    if format_id == 9:
        return struct.pack(f"<{len(values)}b", *values)
    if format_id == 10:
        return bytes(values)
    raise AssertionError(format_id)


class ModelMeshTests(unittest.TestCase):
    def test_bake_blender_space_maps_points_normals_and_bone_translation(self) -> None:
        part = gbm_model_mesh.MeshPart(
            name="part",
            material_index=0,
            positions=np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
            normals=np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
            uvs=np.zeros((1, 2), dtype=np.float32),
            triangles=np.zeros((0, 3), dtype=np.int32),
            joints=None,
            weights=None,
        )
        matrix = np.identity(4, dtype=np.float32)
        matrix[:3, 3] = [10.0, 20.0, 30.0]
        mesh = gbm_model_mesh.MeshData(
            name="m",
            parts=(part,),
            bones=(gbm_model_mesh.Bone("root", -1, matrix),),
            materials=(gbm_model_mesh.MaterialDef(0, "mat_0", None, None),),
            space="engine",
        )

        baked = gbm_model_mesh.bake_blender_space(mesh)

        np.testing.assert_allclose(baked.parts[0].positions[0], [-0.01, 0.03, 0.02])
        np.testing.assert_allclose(baked.parts[0].normals[0], [-1.0, 0.0, 0.0])
        np.testing.assert_allclose(baked.bones[0].world_matrix[:3, 3], [-0.1, 0.3, 0.2])
        self.assertAlmostEqual(float(np.linalg.det(gbm_model_mesh.AXIS_3)), 1.0)
        self.assertEqual(baked.space, "blender")

    def test_vectorized_decode_matches_scalar_decode_for_supported_formats(self) -> None:
        cases = {
            1: ([1.25, -2.5, 3.0], [4.0, 5.5, -6.75]),
            2: ([1024, -512, 256], [0, 2048, -1024]),
            5: ([32767, -32768, 0], [16384, -16384, 8192]),
            8: ([1, 2, 255], [4, 5, 6]),
            9: ([127, -128, 0], [64, -64, 32]),
            10: ([0, 128, 255], [64, 32, 16]),
        }
        for format_id, rows in cases.items():
            with self.subTest(format_id=format_id):
                element = _element(format_id, 3)
                vertex_bytes = b"".join(_pack(format_id, row) for row in rows)
                actual = gbm_model_mesh.vectorized_decode_element(
                    vertex_bytes, 2, element.byte_size, element
                )
                expected = np.array(
                    [
                        gbm_mod_obj_probe.decode_element(
                            vertex_bytes[index * element.byte_size : (index + 1) * element.byte_size],
                            element,
                        )
                        for index in range(2)
                    ],
                    dtype=np.float32,
                )
                np.testing.assert_allclose(actual, expected, rtol=1.0e-6, atol=1.0e-6)


if __name__ == "__main__":
    unittest.main()
