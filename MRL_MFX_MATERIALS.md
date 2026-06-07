# MRL and MFX Material Context

Last updated: 2026-06-07

## Role in the Static Pipeline

The current static FBX uses a practical Blender material:

- `ma320900_BM.png` as base color;
- `ma320900_NM.png` as a normal map;
- one material assigned to the exported mesh.

This is enough to inspect the extracted model visually. Exact in-game shader
semantics remain a separate research task.

## MRL

The sample material resource is:

```text
research_output\320900_first89_v2\character\ma320900\mod\ma320900.mrl
```

Observed state:

- magic is `MRL\0`;
- sample size is 848 bytes;
- resource references include BM and NM texture paths;
- records appear to include material names, colors, scalar parameters, and
  texture bindings.

Full MRL semantic naming is not complete. It is not a blocker because texture
paths and practical material binding are already sufficient for static FBX
export.

## MFX

The global shader package used by the model decoder is:

```text
gundam-breaker-mobile-4-01-03\assets\nativeAndroid\system\shader\ShaderPackage.mfx
```

The current tooling parses input layout objects from MFX. This is required to
decode the MOD vertex streams correctly because primitive records point to MFX
layout IDs.

Validated layouts for the sample:

| Layout | Name | Stride |
|---:|---|---:|
| 14 | `IASkinTB1wt` | 24 |
| 18 | `IASkinTBnwt` | 28 |

The FBX material does not yet reproduce game-specific shader parameters such as
custom masks, emission controls, or exact normal-map conventions.
