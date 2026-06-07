# Tools Reference

Last updated: 2026-06-07

## `tools\gbm_start.py`

Runs the current static pipeline by invoking the focused tools in order:

```text
gbm_arc_extract.py
  -> gbm_tex_to_png.py
  -> gbm_mod_obj_probe.py
  -> gbm_blender_convert.py
```

Typical use from the repository root:

```powershell
python .\tools\gbm_start.py `
  ..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\320900.arc `
  --model-stem ma320900 `
  -o .\out\320900
```

Responsibilities:

- create the standard output layout;
- run ARC extraction and write `_manifest.json`;
- select a MOD file, optionally by `--model-stem`;
- use `tools\ShaderPackage.mfx` by default for vertex layout decoding;
- convert TEX files beside the selected MOD to PNG;
- export bind-pose OBJ;
- call Blender for static FBX export unless `--skip-fbx` is passed.

Useful options:

| Option | Meaning |
|---|---|
| `--model-stem` | Choose a specific model stem such as `ma320900` |
| `--mfx` | Override the default `tools\ShaderPackage.mfx` path |
| `--limit` | Partial extraction limit passed to the ARC extractor |
| `--blender` | Blender executable path |
| `--skip-fbx` | Stop after PNG and OBJ output |
| `--force` | Delete the output root before running |
| `--dry-run` | Print planned commands without executing |

## `tools\gbm_arc_extract.py`

Extracts ARCC v8 archives.

Responsibilities:

- validate `ARCC` magic and version 8;
- decrypt the TOC and payloads with MT-style Blowfish;
- inflate compressed payloads;
- infer extensions from decoded magic;
- write a JSON manifest.

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
--axis-mode blender
```

`--mfx` defaults to `tools\ShaderPackage.mfx`. `-o` can be either a full
`.obj` path or an output directory. When a directory is passed, the exporter
writes `<mod stem>.obj` inside it.

## `tools\gbm_blender_convert.py`

Runs inside Blender and converts OBJ plus PNG textures to FBX.

Responsibilities:

- import OBJ;
- assign BM and optional NM textures;
- render a preview;
- export FBX;
- clear the scene, re-import the FBX, and report round-trip metrics.

For the current static phase, do not pass LMT-related arguments.

## `tools\gbm_lmt_inspect.py`

Inspects LMT motion lists. This tool is kept for research continuity, but LMT
animation is not required for the current static extraction phase.
