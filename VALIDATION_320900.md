# Validation: `ch/320900.arc`

Last updated: 2026-06-07

## Source Archive

```text
com.bandainamcoent.gb_jp\files\dlc\archive\ch\320900.arc
size = 6,812,040 bytes
```

The archive manifest reports 279 entries. The first 89 extracted entries are
enough for the validated static model path.

## Extracted Model Inputs

```text
research_output\320900_first89_v2\character\ma320900\mod\ma320900_BM.tex
research_output\320900_first89_v2\character\ma320900\mod\ma320900_NM.tex
research_output\320900_first89_v2\character\ma320900\mod\ma320900.mrl
research_output\320900_first89_v2\character\ma320900\mod\ma320900.mod
```

The motion file also exists but is not required for the static deliverable:

```text
research_output\320900_first89_v2\motion\ma\ma320900\ma320900.lmt
```

## Texture Validation

Converted texture outputs:

```text
research_output\320900_png_corrected\ma320900_BM.png  726,345 bytes
research_output\320900_png_corrected\ma320900_NM.png  192,776 bytes
```

The BM texture is visually coherent when rendered on the exported model.

## Geometry Validation

Static mesh statistics from Blender:

| Metric | Value |
|---|---:|
| Meshes | 1 |
| Vertices | 52,667 |
| Polygons | 44,867 |
| Loops | 134,601 |
| Materials | 1 |

Source scene bounds:

```text
min = [-8.900418, -2.713187, -0.001194]
max = [ 8.901201,  1.870560, 28.441507]
```

Re-imported FBX bounds:

```text
min = [-8.900418, -2.713193, -0.001195]
max = [ 8.901201,  1.870563, 28.441507]
```

The small numeric differences are normal floating-point and FBX import/export
noise. Topology is preserved exactly.

## Current Validated Output

```text
research_output\320900_fbx_static_phase\ma320900.fbx
research_output\320900_fbx_static_phase\ma320900_BM.png
research_output\320900_fbx_static_phase\ma320900_NM.png
research_output\320900_fbx_static_phase\ma320900_preview.png
research_output\320900_fbx_static_phase\ma320900_fbx_report.json
```
