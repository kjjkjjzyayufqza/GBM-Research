#!/usr/bin/env python3
"""Diagnostic: export a minimal identity-rest armature and dump node rotations.

Isolates what Blender's FBX exporter writes for a root bone whose rest matrix
is identity, under the project's export settings.

Run with Blender:

    blender --background --python tests/probe_minimal_armature_export.py -- out.fbx
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Matrix

argv = sys.argv[sys.argv.index("--") + 1 :]
fbx_path = Path(argv[0]).resolve()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

armature_data = bpy.data.armatures.new("probe_armature")
armature = bpy.data.objects.new("probe_armature", armature_data)
bpy.context.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
root = armature_data.edit_bones.new("Root")
root.matrix = Matrix.Identity(4)
root.length = 0.5
child = armature_data.edit_bones.new("Child")
child.matrix = Matrix.Translation((0.0, 0.0, 1.0))
child.length = 0.5
child.parent = root
bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.export_scene.fbx(
    filepath=str(fbx_path),
    use_selection=True,
    object_types={"ARMATURE"},
    apply_unit_scale=True,
    use_space_transform=True,
    bake_space_transform=False,
    add_leaf_bones=False,
    primary_bone_axis="Y",
    secondary_bone_axis="X",
    axis_forward="Z",
    axis_up="Y",
)

from io_scene_fbx import parse_fbx

elem_root, _ = parse_fbx.parse(str(fbx_path))
objects = next(e for e in elem_root.elems if e.id == b"Objects")
for model in (e for e in objects.elems if e.id == b"Model"):
    name = model.props[1].split(b"\x00")[0].decode("utf-8", "replace")
    kind = model.props[2].decode("utf-8", "replace")
    rotation = (0.0, 0.0, 0.0)
    translation = (0.0, 0.0, 0.0)
    for child_elem in model.elems:
        if child_elem.id != b"Properties70":
            continue
        for prop in child_elem.elems:
            key = prop.props[0].decode("utf-8", "replace")
            if key == "Lcl Rotation":
                rotation = tuple(round(float(v), 3) for v in prop.props[4:7])
            elif key == "Lcl Translation":
                translation = tuple(round(float(v), 3) for v in prop.props[4:7])
    print(f"{kind:>10} {name:<20} rot={rotation} loc={translation}")
