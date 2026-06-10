import importlib.util
import sys
import unittest

from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "gbm_equip_lookup.py"
SPEC = importlib.util.spec_from_file_location("gbm_equip_lookup", MODULE_PATH)
gbm_equip_lookup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gbm_equip_lookup
SPEC.loader.exec_module(gbm_equip_lookup)


def match(
    part_type: int,
    part_type_name: str,
    model_id: int,
    table: str,
) -> gbm_equip_lookup.EquipMatch:
    return gbm_equip_lookup.EquipMatch(
        table=table,
        serial_name="RX-78-2",
        offset=part_type,
        parts_id=11_000_000 + part_type,
        parts_name_id=2_000 + part_type,
        gunpla_id=10_000,
        model_id=model_id,
        parts_type=part_type,
        parts_type_name=part_type_name,
        archive_variants=[f"ch/{model_id}.arc", f"ch/{model_id}_vfx.arc"],
    )


class EquipIndexTests(unittest.TestCase):
    def test_suit_part_filter_excludes_weapons_and_shields(self) -> None:
        matches = [
            match(0, "head", 10_000, "table_head.eth"),
            match(1, "body", 10_000, "table_body.etb"),
            match(6, "long_weapon", 10_100, "table_long_weapon.etwl"),
            match(7, "shield", 12_100, "table_shield.ets"),
        ]

        actual = [item for item in matches if gbm_equip_lookup.is_suit_part(item)]

        self.assertEqual([item.parts_type_name for item in actual], ["head", "body"])

    def test_archive_index_groups_only_supplied_suit_matches(self) -> None:
        rows = gbm_equip_lookup.archive_index_rows(
            [
                match(0, "head", 10_000, "table_head.eth"),
                match(1, "body", 10_000, "table_body.etb"),
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].serial_name, "RX-78-2")
        self.assertEqual(rows[0].gunpla_id, 10_000)
        self.assertEqual(rows[0].model_id, 10_000)
        self.assertEqual(rows[0].primary_ch_archive, "ch/10000.arc")
        self.assertNotIn("12100", rows[0].ch_archives)


if __name__ == "__main__":
    unittest.main()
