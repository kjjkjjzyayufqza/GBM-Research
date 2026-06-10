#!/usr/bin/env python3
"""Diagnostic: check bone-vs-vertex-group alignment inside a generated FBX.

Run with Blender:

    blender --background --python tests/probe_fbx_bone_skin_alignment.py -- model.fbx
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1 :]
fbx_path = Path(argv[0]).resolve()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.fbx(filepath=str(fbx_path))

meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
print(f"meshes={len(meshes)} armatures={len(armatures)}")
print("mesh objects:", sorted(obj.name for obj in meshes))
armature = armatures[0]

group_accum: dict[str, list[float]] = {}
for model in meshes:
    group_names = {group.index: group.name for group in model.vertex_groups}
    world = model.matrix_world
    for vertex in model.data.vertices:
        position = world @ vertex.co
        for element in vertex.groups:
            entry = group_accum.setdefault(
                group_names[element.group], [0.0, 0.0, 0.0, 0.0]
            )
            entry[0] += position.x * element.weight
            entry[1] += position.y * element.weight
            entry[2] += position.z * element.weight
            entry[3] += element.weight

print(
    f"{'bone':>10} {'head_x':>9} {'head_y':>9} {'head_z':>9} "
    f"{'cent_x':>9} {'cent_y':>9} {'cent_z':>9} {'dist':>7}"
)
mismatches = 0
checked = 0
for bone in armature.data.bones:
    entry = group_accum.get(bone.name)
    if entry is None or entry[3] < 1.0:
        continue
    head = armature.matrix_world @ bone.head_local
    cx, cy, cz = (entry[0] / entry[3], entry[1] / entry[3], entry[2] / entry[3])
    dist = ((head.x - cx) ** 2 + (head.y - cy) ** 2 + (head.z - cz) ** 2) ** 0.5
    flag = ""
    if abs(head.x) > 0.03 and abs(cx) > 0.03 and (head.x > 0) != (cx > 0):
        flag = "  <-- X SIGN MISMATCH"
        mismatches += 1
    checked += 1
    print(
        f"{bone.name:>10} {head.x:>9.3f} {head.y:>9.3f} {head.z:>9.3f} "
        f"{cx:>9.3f} {cy:>9.3f} {cz:>9.3f} {dist:>7.3f}{flag}"
    )
print(f"\nchecked={checked} x_sign_mismatches={mismatches}")
