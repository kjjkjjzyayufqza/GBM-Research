# Tools Reference

Last updated: 2026-06-07

Related docs:

- [README.md](README.md) - project entry point and key document index.
- [RESOURCE_NAME_MAPPING.md](RESOURCE_NAME_MAPPING.md) - how serial names map to `ch/*.arc` archives and lookup CSVs.
- [RESOURCE_FORMAT_CATALOG.md#dlc-archive-directories](RESOURCE_FORMAT_CATALOG.md#dlc-archive-directories) - meaning of DLC archive folders.

## `tools\gbm_start.py`

Runs the current static pipeline by invoking the focused tools in order:

```text
gbm_arc_extract.py
  -> gbm_tex_to_png.py
  -> native MeshData decode
  -> native OBJ/FBX/GLB writers
```

Typical all-model export from the repository root:

```powershell
python .\tools\gbm_start.py `
  E:\research\Gundam_Breaker_Mobile\com.bandainamcoent.gb_jp\files\dlc\archive\ch\12235.arc `
  -o .\out\12235
```

Responsibilities:

- create the standard output layout;
- run ARC extraction and write `_manifest.json`;
- select one MOD when `--model-stem` is provided, otherwise export every
  discovered `.mod`;
- place all-model outputs under `out\<arc-stem>\models\<unique-model-name>\...`;
- use `tools\ShaderPackage.mfx` by default for vertex layout decoding;
- convert TEX files beside the selected MOD to PNG;
- decode MOD bind-pose geometry once into in-memory MeshData;
- write OBJ/MTL, FBX, and GLB natively by default;
- keep Blender as an opt-in fallback with `--engine blender`.

Useful options:

| Option | Meaning |
|---|---|
| `--model-stem` | Restrict export to one model stem such as `ma320900` |
| `--mfx` | Override the default `tools\ShaderPackage.mfx` path |
| `--limit` | Partial extraction limit passed to the ARC extractor |
| `--engine` | `native` by default; use `blender` for the legacy converter |
| `--format` | Native comma-separated formats: `obj,fbx,gltf` by default |
| `--blender` | Blender executable path |
| `--skip-fbx` | Stop after PNG and OBJ output |
| `--force` | Delete the output root before running |
| `--dry-run` | Print planned commands without executing |

## `tools\gbm_batch.py`

Batch entry point for drag/drop-style folder workflows.

Use it when you have an archive folder such as:

```text
E:\research\Gundam_Breaker_Mobile\com.bandainamcoent.gb_jp\files\dlc\archive\ma
```

Export every model under that tree to native OBJ, FBX, and GLB:

```powershell
python .\tools\gbm_batch.py `
  E:\research\Gundam_Breaker_Mobile\com.bandainamcoent.gb_jp\files\dlc\archive\ma `
  -o .\out\ma_batch
```

OBJ only:

```powershell
python .\tools\gbm_batch.py `
  E:\research\Gundam_Breaker_Mobile\com.bandainamcoent.gb_jp\files\dlc\archive\ma `
  -o .\out\ma_obj `
  --format obj
```

Extract every ARC without model export:

```powershell
python .\tools\gbm_batch.py `
  E:\research\Gundam_Breaker_Mobile\com.bandainamcoent.gb_jp\files\dlc\archive `
  -o .\out\archive_extract `
  --extract-only
```

Output preserves the input relative archive folders and the ARC stem. For
example, `archive\ma\m800\m810a05_night.arc` becomes:

```text
out\ma_batch\m800\m810a05_night\
  extracted\
  models\
    <model-stem>\
      png\
      obj\
      fbx\
```

Use `--engine blender --format fbx` to route FBX through the legacy Blender
converter. In that mode, `gbm_batch.py` writes `_gbm_blender_jobs.json` and
starts Blender once for all queued FBX jobs.

Drag/drop helpers are available at the repository root:

```text
gbm_batch_export_models.bat
gbm_extract_all_arcs.bat
```

## `tools\gbm_arc_extract.py`

Extracts ARCC v8 archives.

Responsibilities:

- validate `ARCC` magic and version 8;
- decrypt the TOC and payloads with MT-style Blowfish;
- inflate compressed payloads;
- infer extensions from decoded magic;
- write a JSON manifest.

## `tools\gbm_equip_lookup.py`

Searches APK-side equip tables for unit serial names and reports the `model_id`
values that map to numeric `ch/*.arc` archives.

The simpler day-to-day lookup path is to open these generated CSV files:

```text
tools\gbm_archive_lookup_index.csv
tools\gbm_equip_parts_index.csv
tools\gbm_weapon_parts_index.csv
```

The body CSVs preserve the source unit order from `table_body.etb` instead of
sorting `serial_name` alphabetically. By default the generated body CSVs contain
head, body, arms, legs, and backpack. Weapon and shield rows are written to
`gbm_weapon_parts_index.csv`, ordered by source table and original record
offset.

Body parts resolve `model_id -> ch/<model_id>.arc`. Weapon and shield rows use a
separate id range: `weapon_mesh_model_id()` prefixes the table `model_id` with
`2`, so they resolve `model_id 10100 -> ch/210100.arc -> chr210100.mod`. The
`ch_archives` column of `gbm_weapon_parts_index.csv` already holds these `2`-
prefixed weapon meshes. See RESOURCE_NAME_MAPPING.md.

Example:

```powershell
python .\tools\gbm_equip_lookup.py RX-78-2 --exact
python .\tools\gbm_equip_lookup.py RX-78-2 --exact --gunpla-id 10000
python .\tools\gbm_equip_lookup.py --write-indexes
```

Use this before extraction when the human-facing unit name is known but the
numeric archive name is not.

## `tools\gbm_tex_to_png.py`

Converts TEX resources to PNG.

Responsibilities:

- parse TEX v10 headers;
- decode RGBA8888, RGBA4444, ETC2 RGB8, and ETC2 RGBA8 EAC paths used by
  current samples;
- write PNG files and optional manifest data.

## `tools\gbm_mfx_inspect.py`

Inspects shader-package input layouts.

Responsibilities:

- parse `ShaderPackage.mfx`;
- expose input layout names, strides, and semantic declarations;
- provide layout data used by the MOD OBJ exporter.

## `tools\gbm_mod_inspect.py`

Inspects MOD v7 model headers and primitive records.

Responsibilities:

- parse model header fields;
- enumerate primitive records;
- report offsets, counts, and section layout evidence.

## `tools\gbm_mod_obj_probe.py`

Exports a static bind-pose OBJ from a MOD file.

Responsibilities:

- use MFX input layout data to decode vertex streams;
- expand triangle strips;
- convert engine coordinates to Blender coordinates;
- write OBJ, optional MTL, and manifest files.

Current recommended settings:

```text
-o out\obj
--position-mode bind-pose
--axis-mode engine
```

`--mfx` defaults to `tools\ShaderPackage.mfx`. `-o` can be either a full
`.obj` path or an output directory. When a directory is passed, the exporter
writes `<mod stem>.obj` inside it.

`gbm_start.py` intentionally uses `--axis-mode engine` for this intermediate
OBJ so the Blender conversion stage can own the DCC-axis correction.

## `tools\gbm_native_convert.py`

Converts one MOD to OBJ/MTL, FBX, and GLB without Blender.

Responsibilities:

- decode MOD geometry, materials, skeleton, and skin weights into `MeshData`;
- bake the shared Blender-space orientation once;
- build output bytes in memory;
- self-check OBJ, GLB, and FBX structure before writing final files.

Example:

```powershell
python .\tools\gbm_native_convert.py .\out\sample\extracted\character\chr210100\mod\chr210100.mod `
  --mfx .\tools\ShaderPackage.mfx `
  --mrl .\out\sample\extracted\character\chr210100\mod\chr210100.mrl `
  --png-dir .\out\sample\models\png `
  -o .\out\sample\models\chr210100 `
  --format obj,fbx,gltf
```

## `tools\gbm_blender_convert.py`

Runs inside Blender and converts OBJ plus PNG textures to FBX.

Responsibilities:

- import OBJ;
- assign BM and optional NM textures;
- keep the top-level FBX hierarchy flat as `<model>` and optional
  `<model>_armature`;
- render a preview;
- export FBX;
- clear the scene, re-import the FBX, and report round-trip metrics.

For the current static phase, do not pass LMT-related arguments.

## `tools\gbm_lmt_inspect.py`

Inspects LMT motion lists. This tool is kept for research continuity, but LMT
animation is not required for the current static extraction phase.
