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
gbm_gltf_writer = _load("gbm_gltf_writer")


def _mesh(skinned: bool = False) -> "gbm_model_mesh.MeshData":
    joints = weights = None
    bones = ()
    if skinned:
        joints = np.array([[0, 1, 0, 0], [1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.int32)
        weights = np.array(
            [[0.75, 0.25, 0.0, 0.0], [0.5, 0.5, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]],
            dtype=np.float32,
        )
        root = np.identity(4, dtype=np.float32)
        child = np.identity(4, dtype=np.float32)
        child[1, 3] = 2.0
        bones = (
            gbm_model_mesh.Bone("root", -1, root),
            gbm_model_mesh.Bone("child", 0, child),
        )
    part = gbm_model_mesh.MeshPart(
        name="tri",
        material_index=0,
        positions=np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32
        ),
        normals=np.array(
            [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float32
        ),
        uvs=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int32),
        joints=joints,
        weights=weights,
    )
    return gbm_model_mesh.MeshData(
        name="tri",
        parts=(part,),
        bones=bones,
        materials=(gbm_model_mesh.MaterialDef(0, "mat_0", None, None),),
        space="blender",
    )


class GlbWriterTests(unittest.TestCase):
    def test_glb_header_chunks_and_accessor_counts_match_mesh(self) -> None:
        glb = gbm_gltf_writer.write_glb_bytes(_mesh())

        gltf, bin_chunk = gbm_gltf_writer.parse_glb(glb)
        primitive = gltf["meshes"][0]["primitives"][0]

        self.assertEqual(glb[:4], b"glTF")
        self.assertEqual(gltf["asset"]["version"], "2.0")
        self.assertGreater(len(bin_chunk), 0)
        self.assertEqual(
            gltf["accessors"][primitive["attributes"]["POSITION"]]["count"], 3
        )
        self.assertEqual(gltf["accessors"][primitive["indices"]]["count"], 3)
        self.assertEqual(gbm_gltf_writer.validate_glb_bytes(glb)["meshes"], 1)

    def test_glb_skinned_mesh_emits_joints_weights_skin_and_inverse_bind_matrices(self) -> None:
        glb = gbm_gltf_writer.write_glb_bytes(_mesh(skinned=True))

        gltf, _bin_chunk = gbm_gltf_writer.parse_glb(glb)
        primitive = gltf["meshes"][0]["primitives"][0]
        skin = gltf["skins"][0]
        inverse_bind_accessor = gltf["accessors"][skin["inverseBindMatrices"]]

        self.assertIn("JOINTS_0", primitive["attributes"])
        self.assertIn("WEIGHTS_0", primitive["attributes"])
        self.assertEqual(len(gltf["skins"]), 1)
        self.assertEqual(len(skin["joints"]), 2)
        self.assertEqual(inverse_bind_accessor["count"], 2)
        self.assertEqual(len(gltf["nodes"]), 3)


if __name__ == "__main__":
    unittest.main()
