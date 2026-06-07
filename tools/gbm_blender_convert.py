#!/usr/bin/env python3
"""Convert a GBM bind-pose OBJ to textured FBX inside Blender.

Run with Blender, for example:

    blender --background --python tools/gbm_blender_convert.py -- \
      --input-obj model.obj --output-fbx model.fbx --texture model_BM.png
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

TOOLS_DIRECTORY = Path(__file__).resolve().parent
if str(TOOLS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIRECTORY))

from gbm_mfx_inspect import parse_input_layouts
from gbm_lmt_inspect import decode_motion_tracks, sample_track
from gbm_mod_inspect import parse_header, parse_primitive_records
from gbm_mod_obj_probe import (
    derive_bind_decode_matrix,
    matrix_from_bytes,
    multiply_matrix,
    parse_bone_palettes,
)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-obj", required=True, type=Path)
    parser.add_argument("--output-fbx", required=True, type=Path)
    parser.add_argument("--texture", type=Path)
    parser.add_argument("--normal-texture", type=Path)
    parser.add_argument("--mod", type=Path)
    parser.add_argument("--mfx", type=Path)
    parser.add_argument("--lmt", type=Path)
    parser.add_argument("--motion-index", type=int)
    parser.add_argument("--preview-frame", type=int)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--scale", type=float, default=0.01)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for data_collection in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.armatures,
        bpy.data.actions,
    ):
        for item in list(data_collection):
            if item.users == 0:
                data_collection.remove(item)


def import_obj(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(
            filepath=str(path),
            forward_axis="NEGATIVE_Y",
            up_axis="Z",
        )
    else:
        bpy.ops.import_scene.obj(
            filepath=str(path),
            axis_forward="-Y",
            axis_up="Z",
        )
    return [
        obj
        for obj in bpy.data.objects
        if obj not in before and obj.type == "MESH"
    ]


def join_meshes(objects: list[bpy.types.Object]) -> bpy.types.Object:
    if not objects:
        raise RuntimeError("OBJ import produced no mesh objects")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    model = bpy.context.view_layer.objects.active
    model.name = "ma320900"
    model.data.name = "ma320900_mesh"
    return model


def apply_scale(model: bpy.types.Object, scale: float) -> None:
    model.scale = (scale, scale, scale)
    bpy.context.view_layer.objects.active = model
    model.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def copy_texture(source: Path, output_directory: Path) -> Path:
    source = source.resolve()
    destination = (output_directory / source.name).resolve()
    if source != destination:
        shutil.copy2(source, destination)
    return destination


def build_material(
    output_directory: Path,
    texture: Path | None,
    normal_texture: Path | None,
) -> tuple[bpy.types.Material, list[str]]:
    material = bpy.data.materials.new("ma320900_material")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.58
    shader.inputs["Metallic"].default_value = 0.08
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    image_paths: list[str] = []
    if texture:
        copied = copy_texture(texture, output_directory)
        image = bpy.data.images.load(str(copied), check_existing=True)
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.image = image
        image_node.label = "Base Color"
        links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
        emission_input = shader.inputs.get("Emission Color")
        emission_strength = shader.inputs.get("Emission Strength")
        if emission_input and emission_strength:
            links.new(image_node.outputs["Color"], emission_input)
            emission_strength.default_value = 0.35
        image_paths.append(str(copied))

    if normal_texture:
        copied = copy_texture(normal_texture, output_directory)
        image = bpy.data.images.load(str(copied), check_existing=True)
        image.colorspace_settings.name = "Non-Color"
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.image = image
        image_node.label = "Normal"
        normal_node = nodes.new("ShaderNodeNormalMap")
        normal_node.inputs["Strength"].default_value = 0.65
        links.new(image_node.outputs["Color"], normal_node.inputs["Color"])
        links.new(normal_node.outputs["Normal"], shader.inputs["Normal"])
        image_paths.append(str(copied))

    return material, image_paths


def assign_material(model: bpy.types.Object, material: bpy.types.Material) -> None:
    model.data.materials.clear()
    model.data.materials.append(material)
    for polygon in model.data.polygons:
        polygon.material_index = 0
        polygon.use_smooth = True


def find_layout_element(layout: object, semantic: str) -> object | None:
    for element in layout.elements:
        if element.semantic == semantic:
            return element
    return None


def read_skin_weights(
    mod_path: Path,
    mfx_path: Path,
) -> tuple[list[list[tuple[int, float]]], dict[str, object], list[int], list[Matrix]]:
    data = mod_path.read_bytes()
    header = parse_header(mod_path, data)
    records = parse_primitive_records(data, header)
    _, layouts = parse_input_layouts(mfx_path)
    palettes = parse_bone_palettes(data, header)
    _, matrix_delta, parents = derive_bind_decode_matrix(data, header)

    vertex_weights: list[list[tuple[int, float]]] = []
    layout_vertices: Counter[str] = Counter()
    influence_counts: Counter[int] = Counter()
    palette_records: Counter[int] = Counter()
    used_bones: set[int] = set()
    invalid_references: list[dict[str, int]] = []

    for record in records:
        layout_id = record.resource_hash_or_key & 0xFFF
        layout = layouts[layout_id]
        joint = find_layout_element(layout, "Joint")
        weight = find_layout_element(layout, "Weight")
        if joint is None:
            raise ValueError(
                f"primitive {record.index} layout {layout_id} has no Joint semantic"
            )
        if record.field_24 >= len(palettes):
            raise ValueError(
                f"primitive {record.index} uses missing palette {record.field_24}"
            )

        palette = palettes[record.field_24]
        palette_records[record.field_24] += 1
        layout_vertices[f"{layout_id}:{layout.name}"] += record.vertex_count
        vertex_start = (
            header.vertex_buffer_offset
            + record.vertex_base_offset
            + record.vertex_start * record.vertex_size
        )

        for vertex_index in range(record.vertex_count):
            raw_offset = vertex_start + vertex_index * record.vertex_size
            raw_vertex = data[raw_offset : raw_offset + record.vertex_size]
            local_joints = list(
                raw_vertex[
                    joint.byte_offset : joint.byte_offset + joint.component_count
                ]
            )
            local_joints.extend([0] * (4 - len(local_joints)))

            if weight is None:
                raw_weights = [255, 0, 0, 0]
            else:
                explicit = list(
                    raw_vertex[
                        weight.byte_offset : weight.byte_offset
                        + weight.component_count
                    ]
                )
                remainder = 255 - sum(explicit)
                if remainder < 0:
                    raise ValueError(
                        f"primitive {record.index} vertex {vertex_index} "
                        f"has weight sum {sum(explicit)}"
                    )
                raw_weights = explicit + [remainder]
                raw_weights.extend([0] * (4 - len(raw_weights)))

            combined: Counter[int] = Counter()
            for component, raw_weight in enumerate(raw_weights[:4]):
                if raw_weight == 0:
                    continue
                local_joint = local_joints[component]
                if local_joint >= len(palette):
                    invalid_references.append(
                        {
                            "primitive": record.index,
                            "vertex": vertex_index,
                            "component": component,
                            "local_joint": local_joint,
                            "palette": record.field_24,
                        }
                    )
                    continue
                combined[palette[local_joint]] += raw_weight

            total = sum(combined.values())
            influences = [
                (bone_index, raw_weight / total)
                for bone_index, raw_weight in sorted(combined.items())
                if raw_weight > 0
            ]
            if not influences:
                raise ValueError(
                    f"primitive {record.index} vertex {vertex_index} has no valid weights"
                )
            vertex_weights.append(influences)
            influence_counts[len(influences)] += 1
            used_bones.update(bone_index for bone_index, _ in influences)

    bone_info_offset = header.bone_section_offset
    local_matrix_offset = bone_info_offset + header.bone_count * 24
    local_matrices = [
        matrix_from_bytes(data, local_matrix_offset + bone_index * 64)
        for bone_index in range(header.bone_count)
    ]
    world_matrices = []
    for bone_index, local_matrix in enumerate(local_matrices):
        parent = parents[bone_index]
        world_matrices.append(
            local_matrix
            if parent == 0xFF
            else multiply_matrix(local_matrix, world_matrices[parent])
        )

    report = {
        "mod": str(mod_path),
        "mfx": str(mfx_path),
        "bone_count": header.bone_count,
        "vertex_count": len(vertex_weights),
        "layout_vertices": dict(sorted(layout_vertices.items())),
        "palette_records": {
            str(index): count for index, count in sorted(palette_records.items())
        },
        "influence_counts": {
            str(count): vertices for count, vertices in sorted(influence_counts.items())
        },
        "used_bones": len(used_bones),
        "invalid_positive_joint_references": invalid_references,
        "bind_decode_matrix_max_delta": matrix_delta,
        "weight_rule": (
            "Layouts without Weight use Joint.x at 1.0; layouts with three "
            "UNORM8 weights use an implicit fourth weight of 255-sum(xyz)."
        ),
    }
    blender_world_matrices = [Matrix(matrix).transposed() for matrix in world_matrices]
    return vertex_weights, report, parents, blender_world_matrices


def build_armature(
    model: bpy.types.Object,
    mod_path: Path,
    mfx_path: Path,
    scale: float,
) -> tuple[bpy.types.Object, dict[str, object]]:
    vertex_weights, report, parents, source_world_matrices = read_skin_weights(
        mod_path, mfx_path
    )
    if len(vertex_weights) != len(model.data.vertices):
        raise ValueError(
            f"MOD has {len(vertex_weights)} vertices but OBJ has "
            f"{len(model.data.vertices)}"
        )

    axis_matrix = Matrix(
        (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    axis_inverse = axis_matrix.inverted()
    bone_matrices: list[Matrix] = []
    for source_matrix in source_world_matrices:
        converted = axis_matrix @ source_matrix @ axis_inverse
        converted.translation *= scale
        bone_matrices.append(converted)

    armature_data = bpy.data.armatures.new(f"{model.name}_armature")
    armature = bpy.data.objects.new(f"{model.name}_armature", armature_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = []
    for bone_index, matrix in enumerate(bone_matrices):
        edit_bone = armature_data.edit_bones.new(f"Bone_{bone_index:03d}")
        edit_bone.matrix = matrix
        edit_bone.length = max(scale * 10.0, 0.05)
        edit_bones.append(edit_bone)
    for bone_index, parent in enumerate(parents):
        if parent != 0xFF:
            edit_bones[bone_index].parent = edit_bones[parent]
            edit_bones[bone_index].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    vertex_groups = [
        model.vertex_groups.new(name=f"Bone_{bone_index:03d}")
        for bone_index in range(len(bone_matrices))
    ]
    for vertex_index, influences in enumerate(vertex_weights):
        for bone_index, weight in influences:
            vertex_groups[bone_index].add([vertex_index], weight, "REPLACE")

    modifier = model.modifiers.new(name="GBM Armature", type="ARMATURE")
    modifier.object = armature
    model.parent = armature
    model.matrix_parent_inverse = armature.matrix_world.inverted()
    bpy.context.view_layer.update()

    report.update(
        {
            "armature": armature.name,
            "root_bones": sum(parent == 0xFF for parent in parents),
            "vertex_groups": len(model.vertex_groups),
            "rest_pose_status": (
                "Hierarchy and source bind matrices imported; orientation remains "
                "experimental until validated against LMT animation."
            ),
        }
    )
    return armature, report


def apply_lmt_motion(
    armature: bpy.types.Object,
    mod_path: Path,
    lmt_path: Path,
    motion_index: int,
    scale: float,
) -> dict[str, object]:
    mod_data = mod_path.read_bytes()
    header = parse_header(mod_path, mod_data)
    bone_info_offset = header.bone_section_offset
    local_matrix_offset = bone_info_offset + header.bone_count * 24
    parents = [
        mod_data[bone_info_offset + bone_index * 24 + 2]
        for bone_index in range(header.bone_count)
    ]
    source_local_matrices = [
        Matrix(
            matrix_from_bytes(
                mod_data,
                local_matrix_offset + bone_index * 64,
            )
        ).transposed()
        for bone_index in range(header.bone_count)
    ]

    motion = decode_motion_tracks(lmt_path, motion_index, mod_path)
    frame_count = motion["frame_count"]
    if frame_count <= 0:
        raise ValueError(f"motion {motion_index} has no frames")
    tracks = motion["tracks"]
    codec_counts = Counter(track["codec"] for track in tracks)
    usage_counts = Counter(track["usage"] for track in tracks)
    unsupported_usages = sorted(
        {
            track["usage"]
            for track in tracks
            if track["usage"] not in {0, 1, 3, 4}
        }
    )
    if unsupported_usages:
        raise ValueError(
            f"motion {motion_index} uses unsupported channel usages "
            f"{unsupported_usages}"
        )

    rotation_tracks = {
        track["mapped_mod_bone"]: track
        for track in tracks
        if track["usage"] == 0 and track["mapped_mod_bone"] is not None
    }
    translation_tracks = {
        track["mapped_mod_bone"]: track
        for track in tracks
        if track["usage"] == 1 and track["mapped_mod_bone"] is not None
    }
    root_rotation_track = next(
        (track for track in tracks if track["usage"] == 3),
        None,
    )
    root_translation_track = next(
        (track for track in tracks if track["usage"] == 4),
        None,
    )
    unresolved_tracks = [
        track["index"]
        for track in tracks
        if track["usage"] in {0, 1} and track["mapped_mod_bone"] is None
    ]
    if unresolved_tracks:
        raise ValueError(
            f"motion {motion_index} has unmapped joint tracks {unresolved_tracks}"
        )

    axis_matrix = Matrix(
        (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    axis_inverse = axis_matrix.inverted()
    action = bpy.data.actions.new(
        name=f"{armature.name}_motion_{motion_index:02d}"
    )
    armature.animation_data_create()
    armature.animation_data.action = action
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frame_count
    previous_rotations: dict[int, Quaternion] = {}
    previous_root_rotation: Quaternion | None = None

    for source_frame in range(frame_count):
        blender_frame = source_frame + 1
        rotations: dict[int, Quaternion] = {}
        translations: dict[int, Vector] = {}
        for bone_index, track in rotation_tracks.items():
            value = sample_track(track["keys"], source_frame, quaternion=True)
            rotation = Quaternion(
                (value[3], value[0], value[1], value[2])
            ).normalized()
            previous = previous_rotations.get(bone_index)
            if previous is not None and previous.dot(rotation) < 0.0:
                rotation.negate()
            rotations[bone_index] = rotation
            previous_rotations[bone_index] = rotation.copy()
        for bone_index, track in translation_tracks.items():
            value = sample_track(track["keys"], source_frame, quaternion=False)
            translations[bone_index] = Vector(value[:3])

        root_rotation = Quaternion()
        if root_rotation_track:
            value = sample_track(
                root_rotation_track["keys"],
                source_frame,
                quaternion=True,
            )
            root_rotation = Quaternion(
                (value[3], value[0], value[1], value[2])
            ).normalized()
            if (
                previous_root_rotation is not None
                and previous_root_rotation.dot(root_rotation) < 0.0
            ):
                root_rotation.negate()
            previous_root_rotation = root_rotation.copy()
        root_translation = Vector((0.0, 0.0, 0.0))
        if root_translation_track:
            value = sample_track(
                root_translation_track["keys"],
                source_frame,
                quaternion=False,
            )
            root_translation = Vector(value[:3])

        target_world_matrices: list[Matrix] = []
        for bone_index, source_local in enumerate(source_local_matrices):
            source_translation, source_rotation, source_scale = (
                source_local.decompose()
            )
            target_local = Matrix.LocRotScale(
                translations.get(bone_index, source_translation),
                rotations.get(bone_index, source_rotation),
                source_scale,
            )
            parent = parents[bone_index]
            target_world = (
                target_local
                if parent == 0xFF
                else target_world_matrices[parent] @ target_local
            )
            target_world_matrices.append(target_world)

        root_motion = Matrix.LocRotScale(
            root_translation,
            root_rotation,
            Vector((1.0, 1.0, 1.0)),
        )
        scene.frame_set(blender_frame)
        for bone_index, target_world in enumerate(target_world_matrices):
            converted = axis_matrix @ (root_motion @ target_world) @ axis_inverse
            converted.translation *= scale
            pose_bone = armature.pose.bones[f"Bone_{bone_index:03d}"]
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.matrix = converted
        bpy.context.view_layer.update()
        for pose_bone in armature.pose.bones:
            pose_bone.keyframe_insert(
                data_path="location",
                frame=blender_frame,
            )
            pose_bone.keyframe_insert(
                data_path="rotation_quaternion",
                frame=blender_frame,
            )
            pose_bone.keyframe_insert(
                data_path="scale",
                frame=blender_frame,
            )

    for fcurve in action.fcurves:
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = "LINEAR"
    scene.frame_set(1)
    bpy.context.view_layer.update()

    return {
        "lmt": str(lmt_path),
        "motion_index": motion_index,
        "frame_count": frame_count,
        "track_count": motion["track_count"],
        "decoded_key_count": sum(len(track["keys"]) for track in tracks),
        "codec_counts": {
            str(codec): count for codec, count in sorted(codec_counts.items())
        },
        "usage_counts": {
            str(usage): count for usage, count in sorted(usage_counts.items())
        },
        "rotation_tracks": len(rotation_tracks),
        "translation_tracks": len(translation_tracks),
        "root_rotation_tracks": int(root_rotation_track is not None),
        "root_translation_tracks": int(root_translation_track is not None),
        "action": action.name,
        "status": "Decoded LMT motion baked to one Blender key per game frame.",
    }


def world_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [
        obj.matrix_world @ Vector(corner)
        for obj in objects
        if obj.type == "MESH"
        for corner in obj.bound_box
    ]
    if not points:
        raise RuntimeError("No mesh bounds available")
    minimum = Vector(
        tuple(min(point[axis] for point in points) for axis in range(3))
    )
    maximum = Vector(
        tuple(max(point[axis] for point in points) for axis in range(3))
    )
    return minimum, maximum


def add_area_light(
    name: str, location: Vector, target: Vector, energy: float, size: float
) -> None:
    light_data = bpy.data.lights.new(name, type="AREA")
    light_data.energy = energy
    light_data.shape = "DISK"
    light_data.size = size
    light = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(light)
    light.location = location
    light.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()


def render_preview(path: Path, objects: list[bpy.types.Object]) -> None:
    minimum, maximum = world_bounds(objects)
    center = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    radius = max(dimensions.length * 0.5, 1.0)

    camera_data = bpy.data.cameras.new("Preview Camera")
    camera_data.type = "ORTHO"
    camera = bpy.data.objects.new("Preview Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    direction = Vector((1.25, -2.4, 0.72)).normalized()
    camera.location = center + direction * radius * 3.0
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera
    bpy.context.view_layer.update()

    camera_inverse = camera.matrix_world.inverted()
    camera_points = [
        camera_inverse @ (obj.matrix_world @ Vector(corner))
        for obj in objects
        for corner in obj.bound_box
    ]
    width = max(point.x for point in camera_points) - min(
        point.x for point in camera_points
    )
    height = max(point.y for point in camera_points) - min(
        point.y for point in camera_points
    )
    aspect = 900.0 / 1200.0
    camera_data.ortho_scale = max(height, width / aspect) * 1.12

    add_area_light(
        "Key",
        center + Vector((radius * 1.7, -radius * 2.2, radius * 2.4)),
        center,
        4200.0,
        radius * 1.2,
    )
    add_area_light(
        "Fill",
        center + Vector((-radius * 2.0, -radius * 0.4, radius * 1.1)),
        center,
        2200.0,
        radius * 1.5,
    )
    add_area_light(
        "Rim",
        center + Vector((radius * 0.3, radius * 2.0, radius * 2.2)),
        center,
        3200.0,
        radius,
    )

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(path)
    scene.render.image_settings.color_mode = "RGBA"
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.055, 0.055, 0.055, 1.0)
    background.inputs["Strength"].default_value = 0.7
    scene.view_settings.look = "AgX - Medium High Contrast"
    bpy.ops.render.render(write_still=True)


def mesh_stats(objects: list[bpy.types.Object]) -> dict[str, object]:
    meshes = [obj for obj in objects if obj.type == "MESH"]
    minimum, maximum = world_bounds(meshes)
    return {
        "mesh_count": len(meshes),
        "vertices": sum(len(obj.data.vertices) for obj in meshes),
        "polygons": sum(len(obj.data.polygons) for obj in meshes),
        "loops": sum(len(obj.data.loops) for obj in meshes),
        "materials": sorted(
            {
                slot.material.name
                for obj in meshes
                for slot in obj.material_slots
                if slot.material
            }
        ),
        "bounds_min": list(minimum),
        "bounds_max": list(maximum),
    }


def scene_stats(objects: list[bpy.types.Object]) -> dict[str, object]:
    stats = mesh_stats(objects)
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in objects if obj.type == "MESH"]
    stats.update(
        {
            "armature_count": len(armatures),
            "bones": sum(len(obj.data.bones) for obj in armatures),
            "root_bones": sum(
                1
                for obj in armatures
                for bone in obj.data.bones
                if bone.parent is None
            ),
            "vertex_groups": sum(len(obj.vertex_groups) for obj in meshes),
            "armature_modifiers": sum(
                1
                for obj in meshes
                for modifier in obj.modifiers
                if modifier.type == "ARMATURE"
            ),
            "actions": sorted(
                {
                    obj.animation_data.action.name
                    for obj in armatures
                    if obj.animation_data and obj.animation_data.action
                }
            ),
        }
    )
    return stats


def export_fbx(
    path: Path,
    objects: list[bpy.types.Object],
    bake_animation: bool,
) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"MESH", "ARMATURE"},
        apply_unit_scale=True,
        bake_space_transform=False,
        mesh_smooth_type="FACE",
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        use_armature_deform_only=False,
        bake_anim=bake_animation,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=False,
        path_mode="RELATIVE",
        embed_textures=False,
    )


def verify_fbx(path: Path, frame: int) -> dict[str, object]:
    clear_scene()
    bpy.ops.import_scene.fbx(filepath=str(path))
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    imported = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type in {"MESH", "ARMATURE"}
    ]
    return scene_stats(imported)


def main() -> None:
    args = parse_args()
    input_obj = args.input_obj.resolve()
    output_fbx = args.output_fbx.resolve()
    output_fbx.parent.mkdir(parents=True, exist_ok=True)
    preview = args.preview.resolve() if args.preview else None
    report = args.report.resolve() if args.report else None
    if preview:
        preview.parent.mkdir(parents=True, exist_ok=True)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    model = join_meshes(import_obj(input_obj))
    apply_scale(model, args.scale)
    material, image_paths = build_material(
        output_fbx.parent,
        args.texture.resolve() if args.texture else None,
        args.normal_texture.resolve() if args.normal_texture else None,
    )
    assign_material(model, material)
    export_objects = [model]
    skin_report = None
    animation_report = None
    if bool(args.mod) != bool(args.mfx):
        raise ValueError("--mod and --mfx must be provided together")
    if args.lmt and (not args.mod or args.motion_index is None):
        raise ValueError("--lmt requires --mod, --mfx, and --motion-index")
    if args.motion_index is not None and not args.lmt:
        raise ValueError("--motion-index requires --lmt")
    if args.preview_frame is not None and not args.lmt:
        raise ValueError("--preview-frame requires --lmt")
    if args.mod and args.mfx:
        armature, skin_report = build_armature(
            model,
            args.mod.resolve(),
            args.mfx.resolve(),
            args.scale,
        )
        export_objects.append(armature)
        if args.lmt:
            animation_report = apply_lmt_motion(
                armature,
                args.mod.resolve(),
                args.lmt.resolve(),
                args.motion_index,
                args.scale,
            )
    validation_frame = args.preview_frame if args.preview_frame is not None else 1
    if validation_frame < 1:
        raise ValueError("--preview-frame must be at least 1")
    if animation_report and validation_frame > animation_report["frame_count"]:
        raise ValueError(
            f"--preview-frame {validation_frame} exceeds animation frame count "
            f"{animation_report['frame_count']}"
        )
    bpy.context.scene.frame_set(validation_frame)
    bpy.context.view_layer.update()
    source_stats = scene_stats(export_objects)

    if preview:
        render_preview(preview, [model])
    export_fbx(
        output_fbx,
        export_objects,
        bake_animation=animation_report is not None,
    )
    roundtrip_stats = verify_fbx(output_fbx, validation_frame)

    result = {
        "input_obj": str(input_obj),
        "output_fbx": str(output_fbx),
        "fbx_size": output_fbx.stat().st_size,
        "scale": args.scale,
        "validation_frame": validation_frame,
        "image_paths": image_paths,
        "preview": str(preview) if preview else None,
        "skin": skin_report,
        "animation": animation_report,
        "source": source_stats,
        "fbx_roundtrip": roundtrip_stats,
    }
    if report:
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
