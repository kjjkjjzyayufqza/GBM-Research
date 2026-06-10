import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_mrl_inspect.py"
SPEC = importlib.util.spec_from_file_location("gbm_mrl_inspect", MODULE_PATH)
gbm_mrl_inspect = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_mrl_inspect
SPEC.loader.exec_module(gbm_mrl_inspect)

BASE_TAG = 0x117DCDC2
NORMAL_TAG = 0x118DCDC2
MASK_TAG = 0x11ADCDC2
FLOAT_BLOCK_TAG = 0x0C3DCDC0
TEXTURE_TABLE_OFFSET = 0x28
PROPERTY_SIZE = 24


def make_mrl(
    stems: list[str], materials: list[tuple[str, list[tuple[int, int]]]]
) -> bytes:
    """Build a synthetic MRL: texture table, material records, param blocks.

    ``materials`` maps each material name to its parameter cells as
    (tag, value) pairs; texture references use tags with low byte 0xC2 and
    1-based texture indices.
    """
    material_table_offset = TEXTURE_TABLE_OFFSET + len(stems) * 0x90
    param_offset = material_table_offset + len(materials) * 0x30
    param_sizes = [
        (len(cells) + 1) * PROPERTY_SIZE for _, cells in materials
    ]
    data = bytearray(param_offset + sum(param_sizes))
    data[0:4] = b"MRL\x00"
    struct.pack_into("<I", data, 0x04, 0x32)
    struct.pack_into("<I", data, 0x08, len(materials))
    struct.pack_into("<I", data, 0x0C, len(stems))
    struct.pack_into("<Q", data, 0x18, TEXTURE_TABLE_OFFSET)
    struct.pack_into("<Q", data, 0x20, material_table_offset)

    for index, stem in enumerate(stems):
        path = f"character\\chr000019\\mod\\{stem}".encode("ascii")
        start = TEXTURE_TABLE_OFFSET + index * 0x90 + 0x10
        data[start : start + len(path)] = path

    cursor = param_offset
    for index, (name, cells) in enumerate(materials):
        record = material_table_offset + index * 0x30
        struct.pack_into(
            "<I", data, record + 0x08, gbm_mrl_inspect.material_name_hash(name)
        )
        struct.pack_into("<I", data, record + 0x20, cursor)
        for tag, value in cells:
            struct.pack_into(
                "<6I", data, cursor, tag, 0xCDCDCDCD, value, 0, 0, 0
            )
            cursor += PROPERTY_SIZE
        cursor += PROPERTY_SIZE  # zero-tag terminator cell
    return bytes(data)


def write_mrl(directory: str, payload: bytes) -> Path:
    mrl = Path(directory) / "model.mrl"
    mrl.write_bytes(payload)
    return mrl


class PickTextureTests(unittest.TestCase):
    def test_pick_base_prefers_plain_bm_over_paint_variant(self) -> None:
        self.assertEqual(gbm_mrl_inspect.pick_base(["x_P00_BM", "x_BM"]), "x_BM")
        self.assertEqual(gbm_mrl_inspect.pick_base(["x_P00_BM", "x_P30_BM"]), "x_P00_BM")

    def test_pick_normal_returns_nm_or_none(self) -> None:
        self.assertEqual(gbm_mrl_inspect.pick_normal(["x_BM", "x_NM"]), "x_NM")
        self.assertIsNone(gbm_mrl_inspect.pick_normal(["x_BM"]))


class MaterialBindingsTests(unittest.TestCase):
    def test_maps_materials_by_name_hash_not_record_order(self) -> None:
        # Records are stored in a different order than the MOD material name
        # table; binding by table order picks the wrong textures (chr100009).
        payload = make_mrl(
            ["a_BM", "a_NM", "b_BM", "b_NM"],
            [
                ("MatB", [(FLOAT_BLOCK_TAG, 0xE0), (BASE_TAG, 3), (NORMAL_TAG, 4)]),
                ("MatA", [(BASE_TAG, 1), (NORMAL_TAG, 2), (MASK_TAG, 0)]),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            bindings = gbm_mrl_inspect.material_bindings(
                write_mrl(directory, payload), ["MatA", "MatB"]
            )
        self.assertEqual(
            [(b.index, b.name, b.base, b.normal) for b in bindings],
            [(0, "MatA", "a_BM", "a_NM"), (1, "MatB", "b_BM", "b_NM")],
        )

    def test_paint_variant_base_resolves_to_plain_bm(self) -> None:
        payload = make_mrl(
            ["c_P00_BM", "c_BM", "c_NM"],
            [("MatC", [(BASE_TAG, 2), (BASE_TAG, 1), (NORMAL_TAG, 3)])],
        )
        with tempfile.TemporaryDirectory() as directory:
            bindings = gbm_mrl_inspect.material_bindings(
                write_mrl(directory, payload), ["MatC"]
            )
        self.assertEqual(bindings[0].base, "c_BM")
        self.assertEqual(bindings[0].normal, "c_NM")

    def test_missing_material_name_raises(self) -> None:
        payload = make_mrl(["a_BM"], [("MatA", [(BASE_TAG, 1)])])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                gbm_mrl_inspect.material_bindings(
                    write_mrl(directory, payload), ["MatA", "MatMissing"]
                )

    def test_out_of_range_texture_index_raises(self) -> None:
        payload = make_mrl(["a_BM"], [("MatA", [(BASE_TAG, 2)])])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                gbm_mrl_inspect.material_bindings(
                    write_mrl(directory, payload), ["MatA"]
                )

    def test_duplicate_material_name_hash_raises(self) -> None:
        payload = make_mrl(
            ["a_BM"],
            [("MatA", [(BASE_TAG, 1)]), ("MatA", [(BASE_TAG, 1)])],
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                gbm_mrl_inspect.material_bindings(
                    write_mrl(directory, payload), ["MatA"]
                )


if __name__ == "__main__":
    unittest.main()
