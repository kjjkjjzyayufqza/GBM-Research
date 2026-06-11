#!/usr/bin/env python3
"""Blender add-on for loading and exporting GBM ARC assets."""

from __future__ import annotations

bl_info = {
    "name": "GBM ARC Tools",
    "author": "GBM-Research",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > GBM",
    "description": "Import GBM ARC files or lookup serials, then export models with textures.",
    "category": "Import-Export",
}

import sys
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    import gbm_blender_addon_core as core  # noqa: E402
    from gbm_blender_convert import import_job_to_scene  # noqa: E402
except ModuleNotFoundError as exc:
    missing = exc.name or "gbm_blender_addon_core"
    raise ImportError(
        f"Missing GBM add-on module '{missing}'. "
        "Install tools/blender_addon.zip in Blender, not gbm_blender_addon.py alone. "
        "Run: python tools/build_blender_addon.py"
    ) from exc


EXPORTABLE_TYPES = {"MESH", "ARMATURE"}


def addon_settings(context: bpy.types.Context) -> "GBM_PG_Settings":
    return context.scene.gbm_arc_tools


def texture_image_nodes(objects: list[bpy.types.Object]) -> list[object]:
    nodes: list[object] = []
    seen: set[str] = set()
    for obj in objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            material = slot.material
            if not material or not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.bl_idname != "ShaderNodeTexImage" or not node.image:
                    continue
                raw_path = node.image.filepath
                if not raw_path:
                    continue
                path = Path(bpy.path.abspath(raw_path)).resolve()
                key = str(path).casefold()
                if path.is_file() and key not in seen:
                    seen.add(key)
                    nodes.append(node)
    return nodes


def object_texture_paths(objects: list[bpy.types.Object]) -> list[Path]:
    return [
        Path(bpy.path.abspath(node.image.filepath)).resolve()
        for node in texture_image_nodes(objects)
    ]


def copy_textures(objects: list[bpy.types.Object], output_dir: Path) -> int:
    texture_dir = output_dir / "textures"
    copied = 0
    for node in texture_image_nodes(objects):
        destination = core.copy_file_once(
            Path(bpy.path.abspath(node.image.filepath)).resolve(),
            texture_dir,
        )
        node.image.filepath = bpy.path.relpath(str(destination))
        copied += 1
    return copied


def selected_export_objects(context: bpy.types.Context) -> list[bpy.types.Object]:
    objects = [obj for obj in context.selected_objects if obj.type in EXPORTABLE_TYPES]
    extras: list[bpy.types.Object] = []
    for obj in list(objects):
        if obj.type == "MESH":
            if obj.parent and obj.parent.type == "ARMATURE":
                extras.append(obj.parent)
            for modifier in obj.modifiers:
                if modifier.type == "ARMATURE" and modifier.object:
                    extras.append(modifier.object)
    objects.extend(extras)
    unique: list[bpy.types.Object] = []
    seen: set[str] = set()
    for obj in objects:
        if obj.name not in seen:
            seen.add(obj.name)
            unique.append(obj)
    return unique


def collection_export_objects(collection: bpy.types.Collection) -> list[bpy.types.Object]:
    return [obj for obj in collection.all_objects if obj.type in EXPORTABLE_TYPES]


def imported_collections(scene: bpy.types.Scene) -> list[bpy.types.Collection]:
    return sorted(
        [
            collection
            for collection in bpy.data.collections
            if collection.get("gbm_imported") and collection_export_objects(collection)
        ],
        key=lambda item: item.name.lower(),
    )


def export_objects(
    objects: list[bpy.types.Object],
    path: Path,
    format_name: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    normalized = format_name.lower()
    if normalized == "fbx":
        bpy.ops.export_scene.fbx(
            filepath=str(path),
            use_selection=True,
            object_types={"MESH", "ARMATURE"},
            apply_unit_scale=True,
            use_space_transform=True,
            bake_space_transform=False,
            mesh_smooth_type="FACE",
            use_mesh_modifiers=True,
            add_leaf_bones=False,
            primary_bone_axis="Y",
            secondary_bone_axis="X",
            path_mode="RELATIVE",
            embed_textures=False,
            axis_forward="Z",
            axis_up="Y",
        )
        return
    if normalized == "glb":
        bpy.ops.export_scene.gltf(
            filepath=str(path),
            use_selection=True,
            export_format="GLB",
        )
        return
    if normalized == "obj":
        if hasattr(bpy.ops.wm, "obj_export"):
            bpy.ops.wm.obj_export(
                filepath=str(path),
                export_selected_objects=True,
                path_mode="RELATIVE",
            )
        else:
            bpy.ops.export_scene.obj(
                filepath=str(path),
                use_selection=True,
                path_mode="RELATIVE",
            )
        return
    raise ValueError(f"unsupported export format: {format_name}")


def import_arc_paths(context: bpy.types.Context, arc_paths: list[Path]) -> tuple[int, int]:
    settings = addon_settings(context)
    mfx_path = core.resolve_mfx_path(settings.mfx_path)
    settings.mfx_path = str(mfx_path)
    work_root = core.require_directory(settings.work_dir, "Work folder")
    prepared = core.prepare_imports_from_arcs(
        arc_paths,
        work_root=work_root,
        mfx_path=mfx_path,
        lod=settings.lod,
        python_exe=settings.python_exe.strip() or None,
    )
    imported_models = 0
    imported_objects = 0
    for item in prepared:
        result = import_job_to_scene(
            item.job,
            collection_name=item.collection_name,
            texture_output_dir=Path(item.job.output_fbx).parent,
        )
        collection = bpy.data.collections.get(item.collection_name)
        if collection:
            collection["gbm_imported"] = True
            collection["gbm_arc_path"] = str(item.arc_path)
            collection["gbm_model_stem"] = item.model_stem
        imported_models += 1
        imported_objects += len(result["objects"])
    settings.status = f"Imported {imported_models} model(s), {imported_objects} object(s)"
    return imported_models, imported_objects


class GBM_PG_Settings(bpy.types.PropertyGroup):
    archive_root: StringProperty(
        name="Archive Root",
        subtype="DIR_PATH",
        default=str(core.DEFAULT_ARCHIVE_ROOT),
    )
    work_dir: StringProperty(
        name="Work Folder",
        subtype="DIR_PATH",
        default=str(core.DEFAULT_WORK_ROOT),
    )
    mfx_path: StringProperty(
        name="ShaderPackage.mfx",
        subtype="FILE_PATH",
        default=str(core.DEFAULT_MFX),
    )
    python_exe: StringProperty(
        name="Python",
        default="python",
        description="External Python used for ARC/TEX/OBJ preprocessing",
    )
    output_dir: StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
        default="",
    )
    lookup_kind: EnumProperty(
        name="Type",
        items=(("weapon", "Weapon", ""), ("model", "Model", "")),
        default="weapon",
    )
    lookup_serial: StringProperty(name="Serial", default="")
    lookup_contains: BoolProperty(name="Contains", default=False)
    lookup_limit: IntProperty(name="Limit", min=0, default=0)
    lod: IntProperty(name="LOD", min=0, max=2, default=0)
    export_format: EnumProperty(
        name="Format",
        items=(("fbx", "FBX", ""), ("glb", "GLB", ""), ("obj", "OBJ", "")),
        default="fbx",
    )
    export_name: StringProperty(name="Name", default="")
    status: StringProperty(name="Status", default="Ready")


class GBM_OT_ImportArcFiles(bpy.types.Operator):
    bl_idname = "gbm.import_arc_files"
    bl_label = "Import ARC"
    bl_description = "Import one or more GBM .arc files into the current scene"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    filter_glob: StringProperty(default="*.arc", options={"HIDDEN"})

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context):
        if self.files:
            paths = [Path(self.directory) / item.name for item in self.files]
        elif self.filepath:
            paths = [Path(self.filepath)]
        else:
            self.report({"ERROR"}, "No ARC selected")
            return {"CANCELLED"}
        try:
            count, objects = import_arc_paths(context, paths)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {count} model(s), {objects} object(s)")
        return {"FINISHED"}


class GBM_OT_ImportLookup(bpy.types.Operator):
    bl_idname = "gbm.import_lookup"
    bl_label = "Load Serial"
    bl_description = "Load all lookup ARC files for the configured serial"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: bpy.types.Context):
        settings = addon_settings(context)
        serial = settings.lookup_serial.strip()
        if not serial:
            self.report({"ERROR"}, "Serial is required")
            return {"CANCELLED"}
        try:
            archive_root = core.require_directory(settings.archive_root, "Archive root")
            arcs = core.resolve_lookup_arcs(
                kind=settings.lookup_kind,
                serial=serial,
                archive_root=archive_root,
                contains=settings.lookup_contains,
                limit=settings.lookup_limit or None,
            )
            if not arcs:
                raise ValueError(f"No {settings.lookup_kind} ARC found for {serial}")
            count, objects = import_arc_paths(context, arcs)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {count} model(s), {objects} object(s)")
        return {"FINISHED"}


class GBM_OT_ExportSelected(bpy.types.Operator):
    bl_idname = "gbm.export_selected"
    bl_label = "Export Selected"
    bl_description = "Export selected meshes and armatures with referenced textures"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        settings = addon_settings(context)
        objects = selected_export_objects(context)
        if not objects:
            self.report({"ERROR"}, "Select at least one mesh or armature")
            return {"CANCELLED"}
        try:
            output_dir = core.require_directory(settings.output_dir, "Output folder")
            name = settings.export_name.strip() or context.view_layer.objects.active.name
            path = core.export_path(output_dir, name, settings.export_format)
            texture_count = copy_textures(objects, output_dir)
            export_objects(objects, path, settings.export_format)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.status = f"Exported {path.name}, textures {texture_count}"
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class GBM_OT_BatchExportImported(bpy.types.Operator):
    bl_idname = "gbm.batch_export_imported"
    bl_label = "Batch Export"
    bl_description = "Export each imported GBM collection with its textures"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        settings = addon_settings(context)
        collections = imported_collections(context.scene)
        if not collections:
            self.report({"ERROR"}, "No imported GBM collections found")
            return {"CANCELLED"}
        try:
            output_dir = core.require_directory(settings.output_dir, "Output folder")
            total_textures = 0
            for collection in collections:
                objects = collection_export_objects(collection)
                collection_dir = output_dir / core.safe_name(collection.name)
                path = core.export_path(
                    collection_dir,
                    collection.name,
                    settings.export_format,
                )
                total_textures += copy_textures(objects, collection_dir)
                export_objects(objects, path, settings.export_format)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.status = f"Batch exported {len(collections)} collection(s), textures {total_textures}"
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class GBM_PT_Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBM"


class GBM_PT_Setup(GBM_PT_Base, bpy.types.Panel):
    bl_idname = "GBM_PT_setup"
    bl_label = "Setup"

    def draw(self, context: bpy.types.Context) -> None:
        settings = addon_settings(context)
        layout = self.layout
        col = layout.column(align=True)
        col.prop(settings, "archive_root")
        col.prop(settings, "work_dir")
        col.prop(settings, "mfx_path")
        col.prop(settings, "python_exe")
        row = col.row(align=True)
        row.prop(settings, "lod")


class GBM_PT_Import(GBM_PT_Base, bpy.types.Panel):
    bl_idname = "GBM_PT_import"
    bl_label = "Import"

    def draw(self, context: bpy.types.Context) -> None:
        settings = addon_settings(context)
        layout = self.layout
        layout.operator("gbm.import_arc_files", icon="IMPORT")
        box = layout.box()
        box.prop(settings, "lookup_kind", expand=True)
        box.prop(settings, "lookup_serial")
        row = box.row(align=True)
        row.prop(settings, "lookup_contains")
        row.prop(settings, "lookup_limit")
        box.operator("gbm.import_lookup", icon="VIEWZOOM")


class GBM_PT_Export(GBM_PT_Base, bpy.types.Panel):
    bl_idname = "GBM_PT_export"
    bl_label = "Export"

    def draw(self, context: bpy.types.Context) -> None:
        settings = addon_settings(context)
        layout = self.layout
        col = layout.column(align=True)
        col.prop(settings, "output_dir")
        col.prop(settings, "export_format", expand=True)
        col.prop(settings, "export_name")
        row = col.row(align=True)
        row.operator("gbm.export_selected", icon="EXPORT")
        row.operator("gbm.batch_export_imported", icon="PACKAGE")
        layout.label(text=settings.status, icon="INFO")


CLASSES = (
    GBM_PG_Settings,
    GBM_OT_ImportArcFiles,
    GBM_OT_ImportLookup,
    GBM_OT_ExportSelected,
    GBM_OT_BatchExportImported,
    GBM_PT_Setup,
    GBM_PT_Import,
    GBM_PT_Export,
)


def register() -> None:
    unregister()
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError as exc:
            if "already registered" not in str(exc).lower():
                raise
    if not hasattr(bpy.types.Scene, "gbm_arc_tools"):
        bpy.types.Scene.gbm_arc_tools = PointerProperty(type=GBM_PG_Settings)


def unregister() -> None:
    if hasattr(bpy.types.Scene, "gbm_arc_tools"):
        del bpy.types.Scene.gbm_arc_tools
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
