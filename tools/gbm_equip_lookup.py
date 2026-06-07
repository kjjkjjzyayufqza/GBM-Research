#!/usr/bin/env python3
"""Look up GBM equip-table serial names and their model archive ids."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_NATIVE_ANDROID = (
    WORKSPACE_ROOT / "gundam-breaker-mobile-4-01-03" / "assets" / "nativeAndroid"
)
DEFAULT_ARCHIVE_ROOT = (
    WORKSPACE_ROOT / "com.bandainamcoent.gb_jp" / "files" / "dlc" / "archive"
)

VALUE_MARKER = b"\x01\x00\x00\x00"

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


def scan_table(path: Path, query: str, archive_root: Path, exact: bool) -> list[EquipMatch]:
    data = path.read_bytes()
    query_folded = query.casefold()
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
                archive_variants=archive_variants(archive_root, model_id),
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
    parser.add_argument("query", help="Serial name query, for example RX-78-2")
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
    args = parser.parse_args()

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
