#!/usr/bin/env python3
"""Bundle GBM Blender add-on modules into tools/gbm_arc_tools for installation."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ADDON_DIR = TOOLS_DIR / "gbm_arc_tools"

PYTHON_MODULES = (
    "gbm_blender_addon.py",
    "gbm_blender_addon_core.py",
    "gbm_blender_convert.py",
    "gbm_arc_extract.py",
    "gbm_batch.py",
    "gbm_fbx_writer.py",
    "gbm_gltf_writer.py",
    "gbm_lookup_export.py",
    "gbm_lmt_inspect.py",
    "gbm_mfx_inspect.py",
    "gbm_model_mesh.py",
    "gbm_mod_inspect.py",
    "gbm_mod_obj_probe.py",
    "gbm_mrl_inspect.py",
    "gbm_native_convert.py",
    "gbm_obj_writer.py",
    "gbm_start.py",
    "gbm_tex_to_png.py",
)

DATA_FILES = (
    "gbm_archive_lookup_index.csv",
    "gbm_weapon_parts_index.csv",
)

BUNDLE_FILES = PYTHON_MODULES + DATA_FILES


def copy_bundle_files() -> list[Path]:
    ADDON_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in BUNDLE_FILES:
        source = TOOLS_DIR / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing bundle source: {source}")
        destination = ADDON_DIR / name
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def write_zip(output_zip: Path) -> Path:
    copy_bundle_files()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ADDON_DIR.iterdir()):
            if path.is_file():
                archive.write(path, arcname=f"gbm_arc_tools/{path.name}")
    return output_zip


def main() -> int:
    copied = copy_bundle_files()
    zip_path = TOOLS_DIR / "gbm_arc_tools.zip"
    write_zip(zip_path)
    print(f"Bundled {len(copied)} file(s) into {ADDON_DIR}")
    print(f"Created install archive: {zip_path}")
    print("Install in Blender via Edit > Preferences > Add-ons > Install...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
