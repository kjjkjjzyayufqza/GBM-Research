# Static Extraction Pipeline

Last updated: 2026-06-07

This is the currently validated path from a GBM character archive to static FBX
and PNG textures. Prefer the one-command entry point for normal use, and use
the manual steps only when debugging a stage.

## Inputs

```text
..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\320900.arc
tools\ShaderPackage.mfx
```

`tools\ShaderPackage.mfx` is required for MOD vertex layout decoding and is the
default MFX path used by `gbm_start.py`.

## One-Command Pipeline

Run from the `GBM-Research` repository root:

```powershell
python .\tools\gbm_start.py `
  ..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\320900.arc `
  --model-stem ma320900 `
  -o .\out\320900 `
  --force
```

Use `--skip-fbx` when Blender is not available. Use `--dry-run` to print the
planned commands without executing them.

## Manual Pipeline

## Step 1: Extract ARC

```powershell
python .\tools\gbm_arc_extract.py `
  ..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\320900.arc `
  -o .\out\320900\extracted `
  --manifest .\out\320900\extracted\_manifest.json
```

For a full archive extraction, omit `--limit`.

Required sample outputs:

```text
out\320900\extracted\character\ma320900\mod\ma320900_BM.tex
out\320900\extracted\character\ma320900\mod\ma320900_NM.tex
out\320900\extracted\character\ma320900\mod\ma320900.mrl
out\320900\extracted\character\ma320900\mod\ma320900.mod
```

## Step 2: Convert TEX to PNG

```powershell
python .\tools\gbm_tex_to_png.py `
  .\out\320900\extracted\character\ma320900\mod `
  -o .\out\320900\png `
  --manifest .\out\320900\png\_tex_manifest.json
```

Expected PNGs:

```text
out\320900\png\ma320900_BM.png
out\320900\png\ma320900_NM.png
```

## Step 3: Export Bind-Pose OBJ

```powershell
python .\tools\gbm_mod_obj_probe.py `
  .\out\320900\extracted\character\ma320900\mod\ma320900.mod `
  -o .\out\320900\obj `
  --texture .\out\320900\png\ma320900_BM.png `
  --position-mode bind-pose `
  --axis-mode blender `
  --manifest .\out\320900\obj\ma320900_obj_manifest.json
```

## Step 4: Export Static FBX

Run through Blender 4.2:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.2\blender.exe' `
  --background `
  --python .\tools\gbm_blender_convert.py -- `
  --input-obj .\out\320900\obj\ma320900.obj `
  --output-fbx .\out\320900\fbx\ma320900.fbx `
  --texture .\out\320900\png\ma320900_BM.png `
  --normal-texture .\out\320900\png\ma320900_NM.png `
  --preview .\out\320900\fbx\ma320900_preview.png `
  --report .\out\320900\fbx\ma320900_fbx_report.json
```

Do not pass `--lmt` for the current static phase.

## Expected Result

```text
out\320900\fbx\ma320900.fbx
out\320900\fbx\ma320900_BM.png
out\320900\fbx\ma320900_NM.png
out\320900\fbx\ma320900_preview.png
out\320900\fbx\ma320900_fbx_report.json
```

The report should show matching source and re-imported FBX topology:

```text
vertices = 52,667
polygons = 44,867
loops    = 134,601
```
