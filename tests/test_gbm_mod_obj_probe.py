import importlib.util
import sys
import types
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

MODULE_PATH = TOOLS_DIR / "gbm_mod_obj_probe.py"
SPEC = importlib.util.spec_from_file_location("gbm_mod_obj_probe", MODULE_PATH)
gbm_mod_obj_probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_mod_obj_probe
SPEC.loader.exec_module(gbm_mod_obj_probe)


def fake_record(index: int, packed_flags: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(index=index, packed_flags=packed_flags)


class MaterialIndexTests(unittest.TestCase):
    def test_material_index_reads_packed_flags_bits_12_23(self) -> None:
        # bits 12..23 = 1, bits 24..31 (LOD mask) = 0x01
        record = fake_record(0, (0x01 << 24) | (1 << 12))
        self.assertEqual(gbm_mod_obj_probe.material_index(record), 1)


class SelectPrimitivesForLodTests(unittest.TestCase):
    def test_keeps_only_primitives_with_requested_lod_bit(self) -> None:
        records = [
            fake_record(0, 0x01 << 24),  # LOD0 only
            fake_record(1, 0x02 << 24),  # LOD1 only
            fake_record(2, 0x0C << 24),  # LOD2 and LOD3
        ]
        lod0 = gbm_mod_obj_probe.select_primitives_for_lod(records, 0)
        lod2 = gbm_mod_obj_probe.select_primitives_for_lod(records, 2)
        self.assertEqual([r.index for r in lod0], [0])
        self.assertEqual([r.index for r in lod2], [2])

    def test_unmanaged_primitives_with_zero_mask_are_always_kept(self) -> None:
        records = [fake_record(0, 0), fake_record(1, 0)]
        selected = gbm_mod_obj_probe.select_primitives_for_lod(records, 1)
        self.assertEqual([r.index for r in selected], [0, 1])

    def test_no_match_raises(self) -> None:
        records = [fake_record(0, 0x01 << 24)]
        with self.assertRaises(ValueError):
            gbm_mod_obj_probe.select_primitives_for_lod(records, 2)


if __name__ == "__main__":
    unittest.main()
