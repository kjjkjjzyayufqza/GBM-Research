#!/usr/bin/env python3
"""Zip tools/ as a Blender add-on archive (no duplicate subfolder)."""

from __future__ import annotations

import zipfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
OUTPUT_ZIP = TOOLS_DIR / "blender_addon.zip"
ADDON_FOLDER = "tools"

SKIP_NAMES = {
    "__pycache__",
    "gbm_arc_tools",
    "blender_addon.zip",
    "gbm_arc_tools.zip",
}
SKIP_FILES = {
    "build_blender_addon.py",
}


def should_include(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name in SKIP_FILES:
        return False
    if path.suffix.lower() == ".pyc":
        return False
    return not any(part in SKIP_NAMES for part in path.parts)


def write_zip(output_zip: Path) -> tuple[Path, int]:
    if not (TOOLS_DIR / "__init__.py").is_file():
        raise FileNotFoundError(f"Missing add-on entry point: {TOOLS_DIR / '__init__.py'}")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(TOOLS_DIR.rglob("*")):
            if not should_include(path):
                continue
            rel = path.relative_to(TOOLS_DIR)
            archive.write(path, arcname=f"{ADDON_FOLDER}/{rel.as_posix()}")
            count += 1
    return output_zip, count


def main() -> int:
    output_zip, count = write_zip(OUTPUT_ZIP)
    print(f"Packed {count} file(s) from {TOOLS_DIR}")
    print(f"Created install archive: {output_zip}")
    print("Install in Blender via Edit > Preferences > Add-ons > Install...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
