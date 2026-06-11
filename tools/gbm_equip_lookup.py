#!/usr/bin/env python3
"""Look up GBM equip-table serial names and their model archive ids."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_NATIVE_ANDROID = (
    WORKSPACE_ROOT / "gundam-breaker-mobile-4-01-03" / "assets" / "nativeAndroid"
)
DEFAULT_ARCHIVE_ROOT = (
    WORKSPACE_ROOT / "com.bandainamcoent.gb_jp" / "files" / "dlc" / "archive"
)
DEFAULT_ARCHIVE_INDEX = REPO_ROOT / "tools" / "gbm_archive_lookup_index.csv"
DEFAULT_PARTS_INDEX = REPO_ROOT / "tools" / "gbm_equip_parts_index.csv"
DEFAULT_WEAPON_PARTS_INDEX = REPO_ROOT / "tools" / "gbm_weapon_parts_index.csv"

VALUE_MARKER = b"\x01\x00\x00\x00"
EQUIP_TABLE_ORDER = (
    "table_head.eth",
    "table_body.etb",
    "table_arms.eta",
    "table_leg.etl",
    "table_backpack.etbp",
    "table_long_weapon.etwl",
    "table_shield.ets",
    "table_short_weapon.etws",
)
SUIT_PART_TYPES = frozenset({0, 1, 2, 3, 4})
WEAPON_TABLE_ORDER = (
    "table_long_weapon.etwl",
    "table_shield.ets",
    "table_short_weapon.etws",
)
WEAPON_TABLES = frozenset(WEAPON_TABLE_ORDER)
MESH_SKIP_ARCHIVE_SUFFIXES = ("_mot", "_vfx")

PART_TYPE_NAMES = {
    0: "head",
    1: "body",
    2: "arms",
    3: "legs",
    4: "backpack",
    5: "short_weapon",
    6: "long_weapon",
    7: "shield",
}


@dataclass(frozen=True)
class EquipMatch:
    table: str
    serial_name: str
    offset: int
    parts_id: int
    parts_name_id: int
    gunpla_id: int
    model_id: int
    parts_type: int
    parts_type_name: str
    archive_variants: list[str]
    we_archive_variants: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArchiveIndexRow:
    serial_name: str
    gunpla_id: int
    model_id: int
    part_types: str
    parts_count: int
    primary_ch_archive: str
    has_ch_archive: str
    ch_archives: str
    source_tables: str


def is_reasonable_serial(value: str) -> bool:
    if not (2 <= len(value) <= 64):
        return False
    return all(ch.isprintable() and ch not in "\r\n\t" for ch in value)


def collect_previous_int_values(data: bytes, marker_offset: int, limit: int = 12) -> list[int]:
    values: list[int] = []
    cursor = marker_offset - 8
    while cursor >= 0 and len(values) < limit:
        if data[cursor : cursor + 4] != VALUE_MARKER:
            break
        values.append(int.from_bytes(data[cursor + 4 : cursor + 8], "little"))
        cursor -= 8
    return values


def archive_variants(archive_root: Path, model_id: int) -> list[str]:
    ch_dir = archive_root / "ch"
    if not ch_dir.exists():
        return []

    prefix = str(model_id)
    matches = []
    for path in ch_dir.glob(f"{prefix}*.arc"):
        if path.name == f"{prefix}.arc" or path.name.startswith(f"{prefix}_"):
            matches.append(path.relative_to(archive_root).as_posix())
    return sorted(matches)


def mesh_archive_variants(variants: list[str]) -> list[str]:
    """Keep only base mesh archives; drop motion/vfx sibling packs."""

    filtered: list[str] = []
    for ref in variants:
        path = Path(ref.replace("\\", "/"))
        if path.suffix.lower() != ".arc":
            continue
        stem = path.stem.lower()
        if any(stem.endswith(suffix) for suffix in MESH_SKIP_ARCHIVE_SUFFIXES):
            continue
        filtered.append(ref)
    return filtered


def weapon_archive_variants(archive_root: Path, parts_id: int) -> list[str]:
    we_dir = archive_root / "we"
    if not we_dir.exists():
        return []

    archive_path = we_dir / f"{parts_id}.arc"
    if not archive_path.exists():
        return []
    return [archive_path.relative_to(archive_root).as_posix()]


def weapon_mesh_model_id(model_id: int) -> int:
    """Map a weapon/shield table model_id to its ch mesh archive id.

    Weapon and shield meshes live in their own ch range, addressed by prefixing
    the table model_id with ``2``: model_id ``10100`` -> ``ch/210100.arc`` ->
    ``character/chr210100/mod/chr210100.mod``. This is a separate id space from
    suit bodies, where the same numeric ``10100`` is RX-178's body archive.
    """
    return int(f"2{model_id}")


def is_suit_part(match: EquipMatch) -> bool:
    return match.parts_type in SUIT_PART_TYPES


def is_weapon_part(match: EquipMatch) -> bool:
    return match.table in WEAPON_TABLES


def scan_table(
    path: Path,
    query: str | None,
    archive_root: Path,
    exact: bool,
) -> list[EquipMatch]:
    data = path.read_bytes()
    query_folded = query.casefold() if query is not None else None
    matches: list[EquipMatch] = []

    cursor = 0
    while True:
        marker = data.find(VALUE_MARKER, cursor)
        if marker < 0:
            break
        cursor = marker + 1

        string_start = marker + len(VALUE_MARKER)
        string_end = data.find(b"\x00", string_start, string_start + 96)
        if string_end < 0:
            continue

        raw = data[string_start:string_end]
        try:
            serial_name = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        if not is_reasonable_serial(serial_name):
            continue

        if query_folded is not None:
            if exact:
                if serial_name.casefold() != query_folded:
                    continue
            elif query_folded not in serial_name.casefold():
                continue

        previous = collect_previous_int_values(data, marker)
        if len(previous) < 9:
            continue

        parts_id = previous[8]
        parts_name_id = previous[7]
        gunpla_id = previous[6]
        model_id = previous[5]
        parts_type = previous[1]

        if not (0 <= parts_type <= 16):
            continue
        if not (1_000 <= gunpla_id <= 999_999 and 1_000 <= model_id <= 999_999):
            continue
        if not (1_000_000 <= parts_id <= 99_999_999):
            continue

        if path.name in WEAPON_TABLES:
            # Weapon/shield meshes are in ch/2<model_id>.arc, not ch/<model_id>.arc.
            variants = archive_variants(archive_root, weapon_mesh_model_id(model_id))
            we_variants = weapon_archive_variants(archive_root, parts_id)
        else:
            variants = archive_variants(archive_root, model_id)
            we_variants = []

        matches.append(
            EquipMatch(
                table=path.name,
                serial_name=serial_name,
                offset=string_start,
                parts_id=parts_id,
                parts_name_id=parts_name_id,
                gunpla_id=gunpla_id,
                model_id=model_id,
                parts_type=parts_type,
                parts_type_name=PART_TYPE_NAMES.get(parts_type, f"type_{parts_type}"),
                archive_variants=variants,
                we_archive_variants=we_variants,
            )
        )

    return matches


def find_matches(
    native_android: Path,
    archive_root: Path,
    query: str,
    exact: bool,
    gunpla_id: int | None,
    model_id: int | None,
) -> list[EquipMatch]:
    equip_dir = native_android / "tuning" / "equip"
    if not equip_dir.exists():
        raise FileNotFoundError(f"equip table directory not found: {equip_dir}")

    matches: list[EquipMatch] = []
    for table in sorted(equip_dir.glob("table_*.*")):
        matches.extend(scan_table(table, query, archive_root, exact))
    if gunpla_id is not None:
        matches = [match for match in matches if match.gunpla_id == gunpla_id]
    if model_id is not None:
        matches = [match for match in matches if match.model_id == model_id]
    return sorted(
        matches,
        key=lambda item: (
            item.model_id,
            item.parts_type,
            item.table,
            item.parts_id,
            item.serial_name,
        ),
    )


def scan_equip_tables(
    native_android: Path,
    archive_root: Path,
    query: str | None = None,
    exact: bool = False,
) -> list[EquipMatch]:
    equip_dir = native_android / "tuning" / "equip"
    if not equip_dir.exists():
        raise FileNotFoundError(f"equip table directory not found: {equip_dir}")

    matches: list[EquipMatch] = []
    by_name = {table.name: table for table in equip_dir.glob("table_*.*")}
    for table_name in EQUIP_TABLE_ORDER:
        table = by_name.pop(table_name, None)
        if table is not None:
            matches.extend(scan_table(table, query, archive_root, exact))
    for table in by_name.values():
        matches.extend(scan_table(table, query, archive_root, exact))
    return matches


def unit_order(matches: list[EquipMatch]) -> dict[tuple[str, int], int]:
    order: dict[tuple[str, int], int] = {}
    body_matches = [
        match
        for match in matches
        if match.parts_type == 1 and match.table == "table_body.etb"
    ]
    for match in sorted(body_matches, key=lambda item: item.offset):
        order.setdefault((match.serial_name, match.gunpla_id), len(order))
    return order


def ordered_matches(matches: list[EquipMatch]) -> list[EquipMatch]:
    order = unit_order(matches)
    return sorted(
        matches,
        key=lambda item: (
            order.get((item.serial_name, item.gunpla_id), 1_000_000),
            item.gunpla_id,
            item.model_id,
            item.parts_type,
            item.table,
            item.offset,
            item.parts_id,
        ),
    )


def table_order_index(table: str) -> int:
    try:
        return EQUIP_TABLE_ORDER.index(table)
    except ValueError:
        return len(EQUIP_TABLE_ORDER)


def source_ordered_matches(matches: list[EquipMatch]) -> list[EquipMatch]:
    return sorted(
        matches,
        key=lambda item: (
            table_order_index(item.table),
            item.offset,
            item.gunpla_id,
            item.model_id,
            item.parts_id,
        ),
    )


def primary_archive(model_id: int, variants: list[str]) -> str:
    exact = f"ch/{model_id}.arc"
    if exact in variants:
        return exact
    for variant in variants:
        name = Path(variant).name
        if name.endswith(".arc") and "_" not in name.removesuffix(".arc"):
            return variant
    return variants[0] if variants else ""


def archive_index_rows(matches: list[EquipMatch]) -> list[ArchiveIndexRow]:
    groups: dict[tuple[str, int, int], list[EquipMatch]] = {}
    for match in matches:
        groups.setdefault(
            (match.serial_name, match.gunpla_id, match.model_id), []
        ).append(match)

    rows: list[ArchiveIndexRow] = []
    for (serial_name, gunpla_id, model_id), group in groups.items():
        part_types = sorted(
            {match.parts_type_name for match in group},
            key=lambda name: min(
                match.parts_type for match in group if match.parts_type_name == name
            ),
        )
        source_tables = sorted({match.table for match in group})
        variants = sorted(
            {variant for match in group for variant in match.archive_variants}
        )
        rows.append(
            ArchiveIndexRow(
                serial_name=serial_name,
                gunpla_id=gunpla_id,
                model_id=model_id,
                part_types="; ".join(part_types),
                parts_count=len(group),
                primary_ch_archive=primary_archive(model_id, variants),
                has_ch_archive="yes" if variants else "no",
                ch_archives="; ".join(variants),
                source_tables="; ".join(source_tables),
            )
        )
    order = unit_order(matches)
    return sorted(
        rows,
        key=lambda item: (
            order.get((item.serial_name, item.gunpla_id), 1_000_000),
            item.gunpla_id,
            item.model_id,
        ),
    )


PARTS_INDEX_FIELDNAMES = [
    "serial_name",
    "gunpla_id",
    "model_id",
    "part_type",
    "parts_id",
    "parts_name_id",
    "table_file",
    "has_ch_archive",
    "ch_archives",
    "has_we_archive",
    "we_archives",
]
WEAPON_PARTS_INDEX_FIELDNAMES = PARTS_INDEX_FIELDNAMES


def write_parts_index(
    path: Path,
    matches: list[EquipMatch],
    source_order: bool = False,
    weapon_index: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        WEAPON_PARTS_INDEX_FIELDNAMES
        if weapon_index
        else PARTS_INDEX_FIELDNAMES
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        sorted_matches = (
            source_ordered_matches(matches) if source_order else ordered_matches(matches)
        )
        for match in sorted_matches:
            is_weapon = is_weapon_part(match)
            ch_variants = (
                mesh_archive_variants(match.archive_variants)
                if weapon_index
                else match.archive_variants
            )
            row = {
                "serial_name": match.serial_name,
                "gunpla_id": match.gunpla_id,
                "model_id": match.model_id,
                "part_type": match.parts_type_name,
                "parts_id": match.parts_id,
                "parts_name_id": match.parts_name_id,
                "table_file": match.table,
                "has_ch_archive": "yes" if ch_variants else "no",
                "ch_archives": "; ".join(ch_variants),
                "has_we_archive": (
                    "yes" if match.we_archive_variants and is_weapon else "no"
                ),
                "we_archives": (
                    "; ".join(match.we_archive_variants) if is_weapon else ""
                ),
            }
            writer.writerow(row)


def write_archive_index(path: Path, rows: list[ArchiveIndexRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "serial_name",
                "gunpla_id",
                "model_id",
                "part_types",
                "parts_count",
                "primary_ch_archive",
                "has_ch_archive",
                "ch_archives",
                "source_tables",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_indexes(
    native_android: Path,
    archive_root: Path,
    archive_index: Path,
    parts_index: Path,
    weapon_parts_index: Path,
    include_non_suit_parts: bool,
) -> tuple[list[ArchiveIndexRow], list[EquipMatch], list[EquipMatch]]:
    matches = scan_equip_tables(native_android, archive_root)
    weapon_matches = [match for match in matches if is_weapon_part(match)]
    if not include_non_suit_parts:
        matches = [match for match in matches if is_suit_part(match)]

    rows = archive_index_rows(matches)
    write_archive_index(archive_index, rows)
    write_parts_index(parts_index, matches)
    write_parts_index(weapon_parts_index, weapon_matches, source_order=True, weapon_index=True)
    return rows, matches, weapon_matches


def print_summary(matches: list[EquipMatch]) -> None:
    if not matches:
        print("no matches")
        return

    print(
        f"{'serial_name':<18} {'part':<13} {'gunpla_id':>9} "
        f"{'model_id':>9} {'parts_id':>10} {'table':<24} archive_variants"
    )
    print("-" * 120)
    for match in matches:
        variants = ", ".join(match.archive_variants) if match.archive_variants else "-"
        print(
            f"{match.serial_name:<18} {match.parts_type_name:<13} "
            f"{match.gunpla_id:>9} {match.model_id:>9} {match.parts_id:>10} "
            f"{match.table:<24} {variants}"
        )

    print("\nunique model ids:")
    seen: dict[int, set[str]] = {}
    variants_by_model: dict[int, list[str]] = {}
    for match in matches:
        seen.setdefault(match.model_id, set()).add(match.parts_type_name)
        variants_by_model.setdefault(match.model_id, match.archive_variants)

    for model_id in sorted(seen):
        variants = ", ".join(variants_by_model[model_id]) if variants_by_model[model_id] else "-"
        print(f"{model_id}: {', '.join(sorted(seen[model_id]))} -> {variants}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Search GBM nativeAndroid tuning/equip tables for a serial name and "
            "report the model_id values that map to ch/*.arc archives."
        )
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Serial name query, for example RX-78-2",
    )
    parser.add_argument(
        "--native-android",
        type=Path,
        default=DEFAULT_NATIVE_ANDROID,
        help=f"Path to assets/nativeAndroid. Defaults to {DEFAULT_NATIVE_ANDROID}.",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=DEFAULT_ARCHIVE_ROOT,
        help=f"Path to files/dlc/archive. Defaults to {DEFAULT_ARCHIVE_ROOT}.",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Require the serial_name to exactly equal the query.",
    )
    parser.add_argument("--gunpla-id", type=int, help="Only show one gunpla_id.")
    parser.add_argument("--model-id", type=int, help="Only show one model_id.")
    parser.add_argument("--json", action="store_true", help="Write JSON output.")
    parser.add_argument(
        "--write-indexes",
        action="store_true",
        help=(
            "Regenerate the lookup CSV files. By default this writes only suit "
            "body resources from head/body/arms/legs/backpack tables."
        ),
    )
    parser.add_argument(
        "--include-non-suit-parts",
        action="store_true",
        help="When writing indexes, include weapon and shield equip rows too.",
    )
    parser.add_argument(
        "--archive-index",
        type=Path,
        default=DEFAULT_ARCHIVE_INDEX,
        help=f"Archive index CSV path. Defaults to {DEFAULT_ARCHIVE_INDEX}.",
    )
    parser.add_argument(
        "--parts-index",
        type=Path,
        default=DEFAULT_PARTS_INDEX,
        help=f"Part index CSV path. Defaults to {DEFAULT_PARTS_INDEX}.",
    )
    parser.add_argument(
        "--weapon-parts-index",
        type=Path,
        default=DEFAULT_WEAPON_PARTS_INDEX,
        help=(
            "Weapon/shield part index CSV path. Defaults to "
            f"{DEFAULT_WEAPON_PARTS_INDEX}."
        ),
    )
    args = parser.parse_args()

    if args.write_indexes:
        archive_rows, part_rows, weapon_rows = write_indexes(
            args.native_android.resolve(),
            args.archive_root.resolve(),
            args.archive_index.resolve(),
            args.parts_index.resolve(),
            args.weapon_parts_index.resolve(),
            args.include_non_suit_parts,
        )
        print(
            f"wrote {len(archive_rows)} archive rows to {args.archive_index} "
            f"and {len(part_rows)} part rows to {args.parts_index}; "
            f"wrote {len(weapon_rows)} weapon rows to {args.weapon_parts_index}"
        )
        return 0

    if args.query is None:
        parser.error("query is required unless --write-indexes is used")

    matches = find_matches(
        args.native_android.resolve(),
        args.archive_root.resolve(),
        args.query,
        args.exact,
        args.gunpla_id,
        args.model_id,
    )

    if args.json:
        print(json.dumps([asdict(match) for match in matches], indent=2))
    else:
        print_summary(matches)

    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
