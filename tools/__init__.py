"""GBM ARC Tools Blender add-on entry point."""

from __future__ import annotations

import sys
from pathlib import Path

# Blender loads this folder as package "tools"; put sibling modules on sys.path.
_ADDON_DIR = Path(__file__).resolve().parent
_ADDON_PATH = str(_ADDON_DIR)
if _ADDON_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PATH)

bl_info = {
    "name": "GBM ARC Tools",
    "author": "GBM-Research",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > GBM",
    "description": "Import GBM ARC files or lookup serials, then export models with textures.",
    "category": "Import-Export",
}


def register() -> None:
    from gbm_blender_addon import register as _register

    _register()


def unregister() -> None:
    from gbm_blender_addon import unregister as _unregister

    _unregister()
