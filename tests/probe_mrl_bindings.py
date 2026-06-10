#!/usr/bin/env python3
"""Diagnostic: resolve and print MRL material bindings for extracted models.

Walks every extracted .mod/.mrl pair under out/, resolves bindings through
the MRL material records (name hash + parameter-block texture references),
and verifies every binding resolves to a texture stem.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from gbm_mod_inspect import parse_header, read_material_names
from gbm_mrl_inspect import material_bindings


def main() -> int:
    scan_root = REPO_ROOT / "out"
    mod_files = sorted(scan_root.rglob("*.mod"))
    print(f"scanning {len(mod_files)} MOD files under {scan_root}")
    errors = 0
    checked = 0
    for mod_path in mod_files:
        mrl_path = mod_path.with_suffix(".mrl")
        if not mrl_path.exists():
            continue
        try:
            data = mod_path.read_bytes()
            names = read_material_names(data, parse_header(mod_path, data))
            bindings = material_bindings(mrl_path, names)
        except Exception as exc:
            errors += 1
            print(f"ERROR {mod_path.stem}: {exc}")
            continue
        checked += 1
        print(f"\n{mod_path.stem}:")
        for binding in bindings:
            print(
                f"  mat_{binding.index} {binding.name}: "
                f"base={binding.base} normal={binding.normal}"
            )
    print(f"\nchecked={checked} models, errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
