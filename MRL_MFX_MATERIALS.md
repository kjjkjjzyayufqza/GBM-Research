# MRL and MFX Material Context

Last updated: 2026-06-10

## Role in the Static Pipeline

The exporter binds one Blender material per mesh group, driven by the MRL:

- each material gets its base color (`*_BM`) and normal map (`*_NM`);
- a primitive's material is `packed_flags` bits 12..23, an index into the MOD
  material name table;
- the material name's hash selects the MRL material record that lists the
  textures;
- `tools/gbm_mrl_inspect.py` resolves the per-material texture stems.

This matters because a model often has several materials (HEAD, ARM, BACK,
BODY, LEG) and may reference textures owned by other models. For example
`chr000019` is a full mech assembled from five parts and binds the textures of
`chr000010`, `chr000011`, `chr000012`, `chr000014`, and `chr000015`; it ships no
texture of its own. `chr000013` is an arm variant that reuses `chr000012`'s
texture. A single `<stem>_BM` guess is therefore wrong for any multi-material
model or texture-sharing variant.

## MRL Format

```text
0x00  char[4]  magic "MRL\0"
0x04  u32      version (0x32)
0x08  u32      material count
0x0c  u32      texture binding count
0x18  u64      texture table offset (0x90-byte records, path at +0x10)
0x20  u64      material table offset (0x30-byte records)

material record (0x30 bytes):
  +0x08  u32   material name hash: ~crc32(name) of the MOD material name
  +0x20  u32   parameter block offset (file-absolute)

parameter block: 24-byte properties [tag u32, fill u32, value u32, 0,
tag hash u32, 0], terminated by a zero tag. Properties whose tag low byte
is 0xC2 reference the texture table with 1-based indices; value 0 means
the sampler slot is unbound.
```

Bindings are keyed by the material name hash, not by table order. The MOD
material name table (0x80 bytes per name, in `packed_flags` material-index
order) provides the names; each name's `~crc32` hash selects the MRL material
record, and the record's parameter block lists the referenced textures.

The texture table order does NOT follow the MOD material order. chr100009
names HEAD, ARM, BACK, BODY, LEG but stores texture groups as HEAD, ARM, LEG,
BACK, BODY — binding by table order picks the wrong textures for every slot
past ARM. `gbm_mrl_inspect.material_bindings` resolves the exact mapping; the
referenced stems are classified by suffix (`*_NM` is the normal map, plain
`*_BM` is preferred over paint variants `*_P00_BM` / `*_P30_BM` for the base
color).

Material color, scalar parameters, and exact sampler semantics beyond the
texture references remain a separate research task; they are not needed for
the textured static FBX.

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
