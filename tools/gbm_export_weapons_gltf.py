#!/usr/bin/env python3
"""Export clean GLB weapon folders from gbm_weapon_parts_index.csv."""

from __future__ import annotations

from gbm_lookup_export import main


if __name__ == "__main__":
    raise SystemExit(main(default_kind="weapon", default_format="gltf"))
