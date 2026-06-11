# Plan: Blender-free in-memory model export (OBJ / FBX / glTF)

Status: draft / in progress
Owner: GBM-Research tooling
Last updated: 2026-06-11

## 1. Goal

Remove the Blender dependency from the model-export pipeline. Replace the
external `blender --background --python gbm_blender_convert.py` stage with a
**pure-Python, in-memory** path that decodes a MOD once and serializes it to
**OBJ, FBX, and glTF (GLB)** directly. Bytes are built in memory; files touch
disk only at the final write.

Motivation: launching Blender per batch is slow and adds a heavy external
dependency. The geometry decode is already pure Python; only skeleton/skin
assembly and the FBX container live inside Blender today.

## 2. Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Output formats | OBJ + FBX + glTF(GLB), all pure in-memory |
| D2 | Writer coupling | Three independent writer modules, each depends only on `MeshData` + stdlib/numpy. No cross-writer imports. No `bpy`. |
| D3 | FBX strategy | Hand-rolled binary FBX 7400 (`struct` + `zlib`), aligned with Blender's default binary export |
| D4 | glTF strategy | Hand-rolled GLB (JSON chunk + BIN chunk). `pygltflib` is not installed; hand-rolling keeps zero new deps and matches the project's hand-rolled binary style. Swappable later because the writer is isolated. |
| D5 | Geometry speed | numpy-vectorized vertex-format decode (replaces per-vertex `struct.unpack_from` loop) |
| D6 | Preview render | Dropped (no pure-Python EEVEE). Was off by default. |
| D7 | FBX round-trip verify | Replaced by a self-check: re-parse the bytes we just wrote and assert structural counts (vertices / bones / materials). |
| D8 | Blender path | Kept as opt-in fallback (`--engine blender`). New native path is the default (`--engine native`). |
| D9 | Test framework | `unittest` (pytest is not installed), loaded via `importlib` from `tools/`, matching existing `tests/`. |

## 3. Current state (reference)

- `gbm_mod_obj_probe.py` — pure Python, already decodes positions (via bind
  matrices), normals, UVs, material runs, triangle strips, bone parents, bone
  palettes, and per-vertex skin weights. It streams straight to OBJ text and
  keeps no reusable mesh object.
- `gbm_blender_convert.py` — imports `bpy`. Adds: armature build (bone world
  matrices + vertex-group skin), split-by-material, preview render, binary FBX
  export, FBX round-trip verify.
- `gbm_start.py` / `gbm_batch.py` — orchestrators that shell out to Blender via
  `_gbm_blender_jobs.json` batch manifest.

Reusable pure helpers (no `bpy`) from `gbm_mod_obj_probe`: `matrix_from_bytes`,
`multiply_matrix`, `derive_bind_decode_matrix`, `parse_bone_palettes`,
`select_primitives_for_lod`, `decode_element`, `find_element`,
`iter_strip_faces`, `decode_position`, `decode_normal`, `material_index`,
`collect_raw_position_bounds`.

## 4. Target architecture

```
tools/gbm_model_mesh.py    # MOD bytes -> MeshData (numpy). Shared source of truth.
tools/gbm_obj_writer.py    # MeshData -> (obj_bytes, mtl_bytes)
tools/gbm_gltf_writer.py   # MeshData -> glb_bytes
tools/gbm_fbx_writer.py    # MeshData -> fbx_bytes (binary 7400, skin + skeleton)
tools/gbm_native_convert.py# Orchestrate: ARC->PNG->MeshData->{obj,fbx,glb}, disk last
```

CLI surface: `gbm_start.py`, `gbm_batch.py`, `gbm_export_models_*`,
`gbm_export_weapons_*` gain `--engine native|blender` (default `native`) and
`--format obj,fbx,gltf` (default all three for native).

### 4.1 Data contract (`MeshData`)

Source-of-truth geometry is decoded in **engine space**. A `bake_blender_space`
step produces the render-space `MeshData` that all three writers serialize
as-is, so OBJ/FBX/GLB share one orientation and scale.

```
MaterialDef(index:int, name:str, base_png:Path|None, normal_png:Path|None)
Bone(name:str, parent:int(-1 root), world_matrix: np.ndarray (4,4) column-vector)
MeshPart(name:str, material_index:int,
         positions:(V,3)f32, normals:(V,3)f32, uvs:(V,2)f32,
         triangles:(T,3)i32 local 0-based,
         joints:(V,4)i32|None, weights:(V,4)f32|None)
MeshData(name:str, parts:tuple[MeshPart], bones:tuple[Bone],
         materials:tuple[MaterialDef], space:str)  # "engine" | "blender"
```

### 4.2 Axis + scale (match Blender output)

- Point map engine->blender: `(x, y, z) -> (-x, z, y)` (Blender OBJ importer
  forward_axis="Z", up_axis="Y"), then uniform scale `0.01`.
- Axis 3x3 `A = [[-1,0,0],[0,0,1],[0,1,0]]`, `det(A) = +1` -> no triangle
  winding flip; normals get the same rotation.
- Bone world bind matrix: `A4 @ M @ A4^-1`, translation `*= 0.01`
  (matches `convert_bind_matrix`).
- Skin cluster / inverse-bind uses baked (blender-space) bone world matrices:
  `TransformLink = boneWorld`, `Transform = inverse(boneWorld)` (mesh at
  origin); glTF `inverseBindMatrix = inverse(boneWorld)`.

## 5. Format specifics

### OBJ
One `o <part.name>` object per part. `usemtl mat_<i>`. Sidecar `.mtl` with
`map_Kd` / `map_Bump`. Static mesh only (OBJ cannot carry a skeleton), same as
today.

### glTF (GLB)
Single binary buffer. Per part: one mesh primitive with POSITION / NORMAL /
TEXCOORD_0 (+ JOINTS_0 / WEIGHTS_0 when skinned). `nodes` for each bone, one
`skins` entry with `inverseBindMatrices`, `materials` referencing embedded or
external `images`. JSON chunk + BIN chunk, 4-byte aligned.

### FBX (binary 7400)
Node record format: end-offset(u32) num-properties(u32) prop-list-len(u32)
name-len(u8) name props nested-nodes 13-byte null terminator. Property arrays
optionally zlib-deflated. Objects: `FBXHeaderExtension`, `GlobalSettings`,
`Definitions`, `Objects` { `Geometry`(Mesh), `Model`(Mesh per part),
`Material`, `Texture`+`Video`, `Model`(LimbNode per bone),
`NodeAttribute`(LimbNode), `Deformer`(Skin), `Deformer`(Cluster per bone),
`Pose`(BindPose) }, `Connections` (OO/OP). `primary_bone_axis="Y"`,
`axis_forward="Z"`, `axis_up="Y"` baked into the data, matching the Blender
export settings.

## 6. TDD behavior list (vertical slices)

Each slice is one test -> one implementation, in order.

1. [RED written] OBJ writer: MeshData -> obj bytes, one v/vt/vn per part
   vertex, 1-based faces local to part. (tracer bullet)
2. OBJ writer: multiple parts each get own `o` block + `usemtl`; mtl bytes list
   `map_Kd`/`map_Bump` per material.
3. GLB writer: valid `glTF` magic + version 2 + JSON/BIN chunk lengths;
   accessor counts equal part vertex/triangle counts.
4. GLB writer: skinned mesh emits JOINTS_0/WEIGHTS_0, one `skins`, one node per
   bone, inverseBindMatrices count == bone count.
5. FBX writer: valid binary header magic + version 7400; node tree parses;
   `Geometry` vertex count == total part vertices.
6. FBX writer: skinned mesh emits `Deformer`(Skin) + one `Cluster` per used
   bone + `Pose`(BindPose); LimbNode count == bone count.
7. `bake_blender_space`: engine point `(x,y,z)` -> `(-x,z,y)*0.01`; bone world
   translation scaled; det(rotation) == +1 (winding preserved).
8. numpy format decoders parity: vectorized decode == scalar `decode_element`
   for format ids {1,2,5,8,9,10}.
9. `decode_mesh` on a real MOD (probe-style, real fixture from `out/`): total
   vertices/triangles == MOD header fields; part count == material runs.
10. `gbm_native_convert` integration: one MOD -> obj+fbx+glb on disk; self-check
    re-parses each output and asserts counts; disk untouched until final write.

`test_*.py` = unittest unit slices (1-8, synthetic `MeshData`).
`probe_*.py` = real-MOD validation scripts (9-10), following existing
`tests/probe_*` convention.

## 7. Verification (self-check, replaces Blender round-trip)

- OBJ: re-parse text, count v/f, confirm material refs resolve.
- GLB: re-parse JSON chunk, validate accessor/bufferView byte ranges in bounds.
- FBX: re-walk node tree, confirm Geometry/Model/Deformer/Pose counts.
Failure -> raise (no silent degrade), consistent with project error policy.

## 8. Out of scope

- LMT animation baking into FBX/GLB (static bind-pose only, as today).
- EEVEE-quality preview images.
- Removing `gbm_blender_convert.py` (kept as fallback engine).

## 9. Rollout

1. Land `gbm_model_mesh` + three writers + tests (slices 1-8).
2. Land `decode_mesh` + `gbm_native_convert` + probes (slices 9-10).
3. Wire `--engine native` (default) into `gbm_start` / `gbm_batch` / exporters;
   keep `--engine blender`.
4. Update README / TOOLS_REFERENCE / RESOURCE_FORMAT_CATALOG.
```
