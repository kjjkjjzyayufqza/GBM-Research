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
gbm_fbx_writer = _load("gbm_fbx_writer")


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


class FbxWriterTests(unittest.TestCase):
    def test_fbx_header_version_node_tree_and_geometry_vertex_count(self) -> None:
        fbx = gbm_fbx_writer.write_fbx_bytes(_mesh())

        counts = gbm_fbx_writer.validate_fbx_bytes(fbx)

        self.assertTrue(fbx.startswith(gbm_fbx_writer.FBX_MAGIC))
        self.assertEqual(
            struct.unpack_from("<I", fbx, len(gbm_fbx_writer.FBX_MAGIC))[0], 7400
        )
        self.assertEqual(counts["geometry_count"], 1)
        self.assertEqual(counts["geometry_vertices"], 3)

    def test_fbx_skinned_mesh_emits_skin_clusters_bind_pose_and_limb_nodes(self) -> None:
        fbx = gbm_fbx_writer.write_fbx_bytes(_mesh(skinned=True))

        counts = gbm_fbx_writer.validate_fbx_bytes(fbx)

        self.assertEqual(counts["skin_count"], 1)
        self.assertEqual(counts["cluster_count"], 2)
        self.assertEqual(counts["pose_count"], 1)
        self.assertEqual(counts["limb_node_count"], 2)


if __name__ == "__main__":
    unittest.main()
