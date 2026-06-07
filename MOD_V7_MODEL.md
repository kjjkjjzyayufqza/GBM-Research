# MOD v7 Model Format

Last updated: 2026-06-07

## Current Support

`tools\gbm_mod_obj_probe.py` exports a static bind-pose OBJ from the GBM MOD v7
model resource. The validated sample is:

```text
research_output\320900_first89_v2\character\ma320900\mod\ma320900.mod
```

The sample output is:

```text
research_output\320900_bind_pose_corrected\ma320900.obj
```

## Sample Metrics

For `ma320900.mod`:

| Metric | Value |
|---|---:|
| Bones | 91 |
| Primitive records | 75 |
| Vertices | 52,667 |
| Polygons after strip expansion | 44,867 |
| Vertex loops | 134,601 |
| Palettes | 3 |

## Geometry

The model uses 16-bit triangle strips. Repeated indices create degenerate
triangles; no `0xffff` primitive restart markers were found in the validated
sample ranges.

Primitive records are 0x38 bytes. Earlier 0x70-byte interpretations skipped
every second record and were incorrect.

## Vertex Layouts

The sample uses MFX input layouts 14 and 18:

| Layout | Name | Stride | Use |
|---:|---|---:|---|
| 14 | `IASkinTB1wt` | 24 bytes | skinned vertex with one full-weight joint |
| 18 | `IASkinTBnwt` | 28 bytes | skinned vertex with multiple weights |

Static OBJ export uses positions, normals, UVs, and triangle topology. Skinning
data is not required for the current static FBX deliverable.

## Coordinate Conversion

The static export converts engine coordinates to Blender coordinates:

```text
Blender X = engine X
Blender Y = -engine Z
Blender Z = engine Y
scale     = 0.01
```

This conversion is validated by the Blender preview and FBX round-trip bounds.

## Skinning Context

Skin weights and the 91-bone hierarchy have been parsed experimentally:

- 81 bones have weighted vertices;
- layout 14 vertices use `Joint.x` at weight 1.0;
- layout 18 stores three explicit UNORM8 weights plus an implicit fourth weight;
- all positive local joint references in the sample resolve through the palette.

This context is useful for future skeletal FBX work but is not part of the
current static extraction path.
