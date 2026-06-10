# Static Extraction Status

Last updated: 2026-06-07

Related docs:

- [README.md](README.md) - project entry point and key document index.
- [STATIC_EXTRACTION_PIPELINE.md](STATIC_EXTRACTION_PIPELINE.md) - current command sequence.
- [VALIDATION_320900.md](VALIDATION_320900.md) - validation sample details.

## Scope

The current phase targets static model and texture extraction from GBM game
files. The goal is a reliable path from a DLC `.arc` file to:

- decoded files from the archive;
- PNG textures from TEX resources;
- a bind-pose OBJ from MOD geometry;
- a textured static FBX that round-trips through Blender.

Skeleton, skin weights, and LMT animation remain research context. They are not
required for the current model-plus-texture deliverable.

## Confirmed

| Area | Current state | Evidence |
|---|---|---|
| ARCC v8 extraction | Working | `ch/320900.arc` extracts named resources and manifest |
| TEX v10 decoding | Working for sample BM/NM | PNG output and visual preview |
| MOD v7 bind-pose geometry | Working for sample | 52,667 vertices, 44,867 polygons |
| Static FBX export | Working | Blender export and FBX re-import match topology |
| Basic material binding | Working | BM as base color, NM as normal map |
| MFX input layouts | Parsed enough for model decoding | Layout 14 and 18 confirmed |
| MRL material semantics | Partially understood | References are visible; full shader semantics not required yet |

## Current Validation Output

```text
research_output\320900_fbx_static_phase\ma320900.fbx
research_output\320900_fbx_static_phase\ma320900_BM.png
research_output\320900_fbx_static_phase\ma320900_NM.png
research_output\320900_fbx_static_phase\ma320900_preview.png
research_output\320900_fbx_static_phase\ma320900_fbx_report.json
```

Round-trip metrics:

| Metric | Source scene | Re-imported FBX |
|---|---:|---:|
| Meshes | 1 | 1 |
| Vertices | 52,667 | 52,667 |
| Polygons | 44,867 | 44,867 |
| Loops | 134,601 | 134,601 |
| Materials | 1 | 1 |

The preview image renders the textured bind-pose model correctly.

## Deferred

LMT animation is deferred. A dynamic motion experiment produced an FBX action
but did not pass visual validation, so it must not be treated as part of the
working extraction pipeline. This does not affect static mesh or texture output.

## Remaining Static Work

1. Add a single end-to-end wrapper command that accepts one ARC and emits FBX
   plus PNGs.
2. Improve MRL material parsing so per-primitive material assignments are named
   instead of approximated.
3. Batch the static pipeline across more character archives to confirm the
   model decoder generalizes beyond `ch/320900.arc`.
