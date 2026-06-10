#!/usr/bin/env python3
"""Diagnostic: print raw FBX node local rotations (LclRotation properties).

Run with Blender:

    blender --background --python tests/probe_fbx_node_rotations.py -- model.fbx
"""

from __future__ import annotations

import sys
from pathlib import Path

from io_scene_fbx import parse_fbx

argv = sys.argv[sys.argv.index("--") + 1 :]
fbx_path = Path(argv[0]).resolve()

elem_root, _ = parse_fbx.parse(str(fbx_path))


def find_children(element, element_id):
    return [child for child in element.elems if child.id == element_id]


objects = next(e for e in elem_root.elems if e.id == b"Objects")
for model in find_children(objects, b"Model"):
    name = model.props[1].split(b"\x00")[0].decode("utf-8", "replace")
    kind = model.props[2].decode("utf-8", "replace")
    rotation = (0.0, 0.0, 0.0)
    translation = (0.0, 0.0, 0.0)
    properties = find_children(model, b"Properties70")
    if properties:
        for prop in find_children(properties[0], b"P"):
            key = prop.props[0].decode("utf-8", "replace")
            if key == "Lcl Rotation":
                rotation = tuple(round(float(v), 3) for v in prop.props[4:7])
            elif key == "Lcl Translation":
                translation = tuple(round(float(v), 3) for v in prop.props[4:7])
    print(f"{kind:>10} {name:<40} rot={rotation} loc={translation}")
