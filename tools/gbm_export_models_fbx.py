#!/usr/bin/env python3
"""Export clean FBX model folders from gbm_archive_lookup_index.csv."""

from __future__ import annotations

from gbm_lookup_export import main


if __name__ == "__main__":
    raise SystemExit(main(default_kind="model", default_format="fbx"))
