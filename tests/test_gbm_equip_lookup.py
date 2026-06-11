import importlib.util
import sys
import tempfile
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
    serial_name: str = "RX-78-2",
    offset: int | None = None,
) -> gbm_equip_lookup.EquipMatch:
    return gbm_equip_lookup.EquipMatch(
        table=table,
        serial_name=serial_name,
        offset=part_type if offset is None else offset,
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

    def test_weapon_part_filter_keeps_weapon_and_shield_tables(self) -> None:
        matches = [
            match(0, "head", 10_000, "table_head.eth"),
            match(5, "short_weapon", 11_100, "table_short_weapon.etws"),
            match(6, "long_weapon", 10_100, "table_long_weapon.etwl"),
            match(7, "shield", 12_100, "table_shield.ets"),
        ]

        actual = [item for item in matches if gbm_equip_lookup.is_weapon_part(item)]

        self.assertEqual(
            [item.parts_type_name for item in actual],
            ["short_weapon", "long_weapon", "shield"],
        )

    def test_source_ordered_matches_uses_table_order_then_file_offset(self) -> None:
        matches = [
            match(
                5,
                "short_weapon",
                11_100,
                "table_short_weapon.etws",
                serial_name="AAA",
                offset=1,
            ),
            match(
                6,
                "long_weapon",
                10_100,
                "table_long_weapon.etwl",
                serial_name="ZZZ",
                offset=20,
            ),
            match(
                6,
                "long_weapon",
                10_101,
                "table_long_weapon.etwl",
                serial_name="MMM",
                offset=10,
            ),
            match(
                7,
                "shield",
                12_100,
                "table_shield.ets",
                serial_name="BBB",
                offset=1,
            ),
        ]

        actual = gbm_equip_lookup.source_ordered_matches(matches)

        self.assertEqual(
            [(item.table, item.offset, item.serial_name) for item in actual],
            [
                ("table_long_weapon.etwl", 10, "MMM"),
                ("table_long_weapon.etwl", 20, "ZZZ"),
                ("table_shield.ets", 1, "BBB"),
                ("table_short_weapon.etws", 1, "AAA"),
            ],
        )

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

    def test_weapon_archive_variants_use_we_parts_id_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp)
            we_dir = archive_root / "we"
            we_dir.mkdir()
            (we_dir / "31000006.arc").write_bytes(b"ARCC")

            actual = gbm_equip_lookup.weapon_archive_variants(
                archive_root, 31_000_006
            )

        self.assertEqual(actual, ["we/31000006.arc"])

    def test_mesh_archive_variants_drops_mot_and_vfx_siblings(self) -> None:
        actual = gbm_equip_lookup.mesh_archive_variants(
            [
                "ch/10300.arc",
                "ch/10300_mot.arc",
                "ch/10300_vfx.arc",
            ]
        )

        self.assertEqual(actual, ["ch/10300.arc"])

    def test_write_weapon_parts_index_writes_we_archives(self) -> None:
        weapon = gbm_equip_lookup.EquipMatch(
            table="table_long_weapon.etwl",
            serial_name="RX-78-2",
            offset=0,
            parts_id=31_000_006,
            parts_name_id=1591,
            gunpla_id=10_000,
            model_id=10_600,
            parts_type=6,
            parts_type_name="long_weapon",
            archive_variants=["ch/10600.arc", "ch/10600_vfx.arc"],
            we_archive_variants=["we/31000006.arc"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "weapons.csv"
            gbm_equip_lookup.write_parts_index(
                output, [weapon], source_order=True, weapon_index=True
            )
            rows = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            rows[0],
            "serial_name,gunpla_id,model_id,part_type,parts_id,parts_name_id,"
            "table_file,has_ch_archive,ch_archives,has_we_archive,we_archives",
        )
        self.assertTrue(
            rows[1].endswith("yes,ch/10600.arc,yes,we/31000006.arc")
        )


if __name__ == "__main__":
    unittest.main()
