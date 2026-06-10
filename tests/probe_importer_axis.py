#!/usr/bin/env python3
"""Diagnostic: measure the exact transform Blender's OBJ importer applies.

Imports a single triangle with distinct coordinates using the same importer
settings as gbm_blender_convert.import_obj, then prints the resulting
world-space vertex coordinates. Also rebuilds the chr100009 conversion scene
(without FBX export) and checks bone-vs-skin alignment before export.

Run with Blender:

    blender --background --python tests/probe_importer_axis.py -- chr100009.obj chr100009.mod
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import bpy

TESTS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TESTS_DIR.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import gbm_blender_convert as conv

argv = sys.argv[sys.argv.index("--") + 1 :]
obj_path = Path(argv[0]).resolve()
mod_path = Path(argv[1]).resolve()

# --- Part 1: importer axis behavior on a known triangle ---
with tempfile.TemporaryDirectory() as tmp:
    triangle = Path(tmp) / "triangle.obj"
    triangle.write_text(
        "v 1.0 2.0 3.0\n"
        "v 1.0 2.0 4.0\n"
        "v 2.0 2.0 3.0\n"
        "f 1 2 3\n",
        encoding="utf-8",
    )
    conv.clear_scene()
    objects = conv.import_obj(triangle)
    model = objects[0]
    print("=== importer axis probe (forward_axis=Z, up_axis=Y) ===")
    for vertex in model.data.vertices:
        world = model.matrix_world @ vertex.co
        print(
            f"source ? -> world ({world.x:+.3f}, {world.y:+.3f}, {world.z:+.3f})"
        )
    print("expected if (x,y,z)->(-x,z,y): (-1,3,2) (-1,4,2) (-2,3,2)")
    print("expected if (x,y,z)->(x,-z,y): (1,-3,2) (1,-4,2) (2,-3,2)")

# --- Part 2: in-scene alignment before FBX export ---
conv.clear_scene()
model = conv.join_meshes(conv.import_obj(obj_path), obj_path.stem)
conv.apply_import_rotation(model)
conv.apply_scale(model, 0.01)
armature, report = conv.build_armature(
    model, mod_path, TOOLS_DIR / "ShaderPackage.mfx", 0.01, 0, "engine"
)

group_names = {group.index: group.name for group in model.vertex_groups}
accum: dict[str, list[float]] = {
    group.name: [0.0, 0.0, 0.0, 0.0] for group in model.vertex_groups
}
world = model.matrix_world
for vertex in model.data.vertices:
    position = world @ vertex.co
    for element in vertex.groups:
        entry = accum[group_names[element.group]]
        entry[0] += position.x * element.weight
        entry[1] += position.y * element.weight
        entry[2] += position.z * element.weight
        entry[3] += element.weight

print("=== in-scene alignment before export ===")
mismatches = 0
checked = 0
for bone in armature.data.bones:
    entry = accum.get(bone.name)
    if entry is None or entry[3] < 1.0:
        continue
    head = armature.matrix_world @ bone.head_local
    cx = entry[0] / entry[3]
    cy = entry[1] / entry[3]
    checked += 1
    x_flip = abs(head.x) > 0.03 and abs(cx) > 0.03 and (head.x > 0) != (cx > 0)
    y_flip = abs(head.y) > 0.03 and abs(cy) > 0.03 and (head.y > 0) != (cy > 0)
    if x_flip or y_flip:
        mismatches += 1
        print(
            f"{bone.name}: head=({head.x:+.3f},{head.y:+.3f}) "
            f"centroid=({cx:+.3f},{cy:+.3f})"
            f"{'  X-FLIP' if x_flip else ''}{'  Y-FLIP' if y_flip else ''}"
        )
print(f"checked={checked} mismatches={mismatches}")
