# Gundam Breaker Mobile Resource Architecture Research

Last updated: 2026-06-07

Workspace: `E:\research\Gundam_Breaker_Mobile`

Related docs:

- [README.md](README.md) - project entry point and key document index.
- [RESOURCE_FORMAT_CATALOG.md](RESOURCE_FORMAT_CATALOG.md) - current concise format catalog.
- [RESOURCE_NAME_MAPPING.md](RESOURCE_NAME_MAPPING.md) - human name to archive lookup notes.

## Objective

The project goal is a reproducible extraction pipeline for Gundam Breaker
Mobile (GBM) Android resources:

```text
ARCC v8 archive
  -> decrypted and decompressed native resources
  -> TEX to PNG
  -> MOD + MRL + MFX to a textured model
  -> FBX
```

The current phase produces PNG textures and a validated static bind-pose FBX
for `ch/320900.arc`. LMT animation and animated FBX export are explicitly
deferred so the model-plus-texture extraction path can stay stable.

Focused notes have been split into smaller files under `research\README.md`.
This file remains the comprehensive historical research log.

## Current Status

| Area | Status | Evidence |
|---|---|---|
| ARCC v8 header and TOC | Confirmed | `rArchive::load`, sample validation |
| Blowfish key and byte order | Confirmed | `libGUNS.so`, full archive extraction |
| zlib payload handling | Confirmed | 126/126 entries from `4127702.arc` |
| TEX 0x01/0x07/0x14/0x15 | Confirmed | `rTexture::load`, GPU format table, visual checks |
| MFX object/input-layout parsing | Confirmed for input layouts | `rShader::load`, 53 parsed layouts |
| MOD v7 geometry/topology | Confirmed for the sample | counts, bounds, Blender render |
| MOD bind-pose position decode | Confirmed | bone matrices converge to one decode transform |
| MRL resource references | Confirmed | BM/NM paths and 0x90-byte records |
| Static textured FBX | Confirmed | Blender export and FBX round-trip import |
| MOD skeleton and weights | Confirmed for the sample | 91-bone hierarchy, palettes, 52,667 weighted vertices |
| Skinned bind-pose FBX | Experimental, out of current phase | 91 bones, 81 used bones, FBX round-trip validation |
| LMT structure | Deferred context | loader, runtime setup, sample parser |
| LMT packed curve decoding | Deferred | not required for static model and texture output |
| Full material semantics | Incomplete | shader parameter block still unnamed |
| Animated FBX | Deferred | action export is not part of the current milestone |

## Project Inventory

Important paths:

| Path | Purpose |
|---|---|
| `com.bandainamcoent.gb_jp\files\dlc\archive` | 15,180 DLC archives |
| `gundam-breaker-mobile-4-01-03` | Extracted APK |
| `gundam-breaker-mobile-4-01-03\lib\arm64-v8a\libGUNS.so` | Main native engine binary |
| `gundam-breaker-mobile-4-01-03\assets\nativeAndroid` | Unpacked base resources |
| `tools` | Extraction and conversion scripts |
| `research_output` | Generated probes, PNGs, OBJ, FBX, and reports |

Archive category counts:

| Directory | ARC count | Likely role |
|---|---:|---|
| `mi` | 3967 | missions, schedulers, FSM, camera motion |
| `ch` | 3162 | characters, mobile suits, motion, sound |
| `ex` | 2867 | EX skills and VFX bundles |
| `we` | 1901 | weapons |
| `pmi` | 1100 | mission-related data; exact naming unresolved |
| `sps` | 795 | special resources; exact naming unresolved |
| `pe` | 427 | parts/equipment-related data |
| `bo` | 396 | boss or battle object data |
| `st` | 259 | story/event data |
| `ra` | 130 | category unresolved |
| `ma` | 86 | mobile armor or related data |
| `co` | 55 | common data |
| `ar` | 28 | AR-related data |
| `sc` | 7 | category unresolved |

GBM uses Capcom MT Framework-derived resource classes plus game-specific
extensions. It is not a Unity asset pipeline.

## Evidence Policy

This document uses three evidence levels:

- **Confirmed**: supported by IDA pseudocode/disassembly and matching sample
  behavior.
- **Observed**: consistent in current files but not yet tied to complete loader
  semantics.
- **Hypothesis**: a working name or interpretation that still needs proof.

## ARCC v8 Archive Architecture

### Header

GBM DLC archives use:

```text
0x00  char[4]  magic = "ARCC"
0x04  u16      version = 8
0x06  u16      file_count
0x08  bytes    encrypted_toc[file_count * 0x90]
...   bytes    encrypted entry payloads
```

`rArchive::load(MtStream&)` at `0x1bb8644` accepts `ARC`, `ARCS`, and `ARCC`
magic variants. GBM DLC samples use `ARCC`, version 8.

### Decrypted TOC Entry

Each GBM entry is `0x90` bytes:

```text
0x00  char[0x80]  archive path, null terminated
0x80  u32         resource type code / DTI hash
0x84  u32         encrypted payload size
0x88  u32         size and flags
0x8c  u32         absolute payload offset
```

Confirmed `size_flags` handling:

```text
uncompressed_size = size_flags & 0x0fffffff
is_zlib_compressed = (size_flags & 0x40000000) != 0
```

### Blowfish Key

The runtime key buffer recovered from `sResourceManager` contains a null byte
after 19 bytes. `MtCipher::setKeyString` therefore uses this key:

```text
c6 c8 51 1e bd ca e0 97 fd b7 46 84 af 51 cf cd 83 5f e0
```

Hex form used by the extractor:

```text
c6c8511ebdcae097fdb74684af51cfcd835fe0
```

### Block Transform

The TOC and every payload use the same MT-style Blowfish ECB transform:

1. Read one encrypted 8-byte block as two little-endian `u32` values.
2. Repack both words as big-endian.
3. Run Blowfish ECB decrypt.
4. Read the result as two big-endian `u32` values.
5. Write both words as little-endian.
6. If the compression bit is set, run zlib decompression.

### Validation Samples

`ex/4127702.arc`:

| Field | Value |
|---|---:|
| Archive size | 1,533,072 bytes |
| Version | 8 |
| File count | 126 |
| TOC size | 18,144 bytes |
| Extracted entries | 126 |
| Failed entries | 0 |

Extracted resource counts:

| Extension | Count |
|---|---:|
| `.tex` | 68 |
| `.bmb` | 25 |
| `.m3r` | 14 |
| `.efl` | 9 |
| `.ean` | 4 |
| `.xfs` | 2 |
| `.lcm` | 2 |
| `.sdl` | 2 |

`4127702.arc` is an EX-skill/VFX package, not a complete character model
package.

`ch/320900.arc` contains the model test set:

| Index | Type code | Resource |
|---:|---:|---|
| 0 | `0x241f5deb` | `ma320900_BM.tex` |
| 1 | `0x241f5deb` | `ma320900_NM.tex` |
| 2 | `0x2749c8a8` | `ma320900.mrl` |
| 3 | `0x58a15856` | `ma320900.mod` |

## Native Resource Format Catalog

The following table records formats observed in GBM or confirmed through
engine `getExt()` methods.

| Magic | Extension | Engine class / role | Status |
|---|---|---|---|
| `ARCC` | `.arc` | `rArchive` | archive fully supported |
| `TEX ` | `.tex` | `rTexture` | main formats supported |
| `MOD\0` | `.mod` | `rModel` | static geometry supported |
| `MRL\0` | `.mrl` | `rMaterial` | references parsed; parameters partial |
| `MFX\0` | `.mfx` | `rShader` | input layouts parsed |
| `LMT\0` | `.lmt` | `rMotionList` | motion and track records parsed |
| `LCM\0` | `.lcm` | `rCameraList` | camera motion; opaque payload |
| `SDL\0` | `.sdl` | `rScheduler` | scheduler data; opaque payload |
| `GLD\0` | `.gld` | mission path/grid data | header observed |
| `geo3` | `.geo3` | `rGeometry3` | geometry/collision-related; opaque |
| `XFS\0` | `.xfs` | serialized FSM/property container | header observed |
| `PRPZ` | `.prp` | property container | may wrap serialized data |
| `GUI\0` | `.gui` | `rGUI` | UI layout/resource |
| `GMD\0` | `.gmd` | GUI/game messages | text/data resource |
| `GFD\0` | `.gfd` | GUI/font data | partial identification |
| `IBMB` | `.bmb` | `rBishamonBMB` | Bishamon VFX binary |
| `BR3M` | `.m3r` | `rBishamonM3R` | Bishamon VFX model |
| `EFL\0` | `.efl` | `rEffectList` | effect list |
| `EAN\0` | `.ean` | `rEffectAnim` | effect animation |
| `FWSE` | `.sew` | sound wrapper/source | opaque |
| `OggS` | `.ogg` | Ogg Vorbis | standard audio |
| `SBKR` | `.sbkr` | `rSoundBank` | sound bank request/container |
| `SRQR` | `.srqr` | `rSoundRequest` | sound request |
| `SSQR` | `.ssqr` | `rSoundSequenceSe` | sound sequence request |

### MIT vs LMT

No `MIT\0` magic, `.mit` extension, loader, or immediate constant has been
found in the APK, extracted samples, or `libGUNS.so`.

The character motion format is **LMT**, not MIT:

```text
magic       = "LMT\0"
engine type = rMotionList
extension   = "lmt"
version     = 68 in the GBM sample
```

If a real `.mit` sample is found later it should be treated as a separate
format, but current evidence points to a transcription of `LMT`.

## TEX v10 Architecture

### Loader Evidence

`rTexture::load(MtStream&)` is at `0x1be6bc0`.

The format ID is the single byte at header offset `0x06`. It indexes
`nDraw::Texture::mFormatTable`, whose records are `0x20` bytes.

Confirmed mappings:

| Format ID | GPU format/type | Storage |
|---:|---|---|
| `0x01` | RGBA8 / unsigned byte | 4 bytes per pixel |
| `0x07` | RGBA / unsigned short 4-4-4-4 | 2 bytes per pixel |
| `0x14` | `GL_COMPRESSED_RGB8_ETC2` (`0x9274`) | 8 bytes per 4x4 block |
| `0x15` | `GL_COMPRESSED_RGBA8_ETC2_EAC` (`0x9278`) | 16 bytes per 4x4 block |

The old ATC interpretation was wrong. It produced noisy images because the
payload is ETC2.

### Header

Current v10 interpretation:

```text
0x00  char[4]  magic = "TEX "
0x04  u16      version = 10
0x06  u8       format_id
0x07  u8       format/storage flags
0x08  u16      attributes
0x0a  u16      flags or reserved
0x0c  u16      width
0x0e  u16      packed height/flags
0x10  u32[4]   observed mip/data offsets
0x20  u32[3]   reserved/optional offsets in current samples
0x2c  u32      payload size
0x30  bytes    texture payload
```

For current 2D samples:

```text
height = (packed_height & 0x03ff) << 3
```

The complete ETC2 mip chain follows at `0x30`. For the 1024x1024 RGB8 sample,
the payload is exactly 699,064 bytes, matching all mip levels down to the
minimum 4x4 block.

### Decoder Details

`texture2ddecoder` returns BGRA bytes. The conversion script swaps red and blue
before creating an RGBA Pillow image.

`RGBA4444` follows OpenGL `GL_UNSIGNED_SHORT_4_4_4_4` bit order:

```text
bits 15..12 = R
bits 11..8  = G
bits 7..4   = B
bits 3..0   = A
```

### Validation

Corrected output:

```text
research_output\320900_png_corrected\ma320900_BM.png
research_output\320900_png_corrected\ma320900_NM.png
research_output\4127702_png_corrected
```

Results:

| Input | Converted | Failed |
|---|---:|---:|
| `4127702` VFX textures | 68 | 0 |
| `ma320900` model textures | 2 | 0 |

Visual checks show:

- a coherent base-color/mask atlas for `ma320900_BM`;
- a valid tangent-space normal map for `ma320900_NM`;
- coherent alpha/effect shapes in ETC2 RGBA VFX textures.

## MFX v54 Shader Package Architecture

`rShader::load(MtStream&)` at `0x1ca976c` accepts:

```text
magic                 = "MFX\0"
u16 at 0x04           = 0
data version at 0x06  = 54
```

Observed `ShaderPackage.mfx` header:

```text
0x00  char[4]  magic = "MFX\0"
0x04  u16      zero
0x06  u16      version = 54
0x08  u32      observed 1
0x0c  u32      object_count = 678
0x10  u32[4]   object category counts
0x20  u64      string_table_offset = 0x0bc064
0x28  u64[]    object offsets; index 0 is null
```

The loader converts file-relative offsets to in-memory pointers. The package
contains 53 input-layout objects.

### Input Layout Object

For object type 6:

```text
0x10  packed object type/flags; low 6 bits are 6
0x28  u16 element_count
0x2a  u16 stored_stride
0x38  INPUT_ELEMENT[element_count]
```

Each input element is 16 bytes:

```text
0x00  u64  semantic string offset
0x08  u32  packed declaration
0x0c  u32  padding/reserved
```

Packed declaration:

```text
bits 0..5    semantic index
bits 6..10   data format
bits 11..17  component count
bits 18..31  byte offset
```

Confirmed data formats used by the sample:

| ID | Meaning |
|---:|---|
| 2 | signed 16-bit fixed point, divide by 1024 |
| 5 | signed normalized 16-bit |
| 8 | unsigned 8-bit integer |
| 9 | signed normalized 8-bit |
| 10 | unsigned normalized 8-bit |

All 53 parsed layouts have matching stored and calculated strides.

### Layout 14: IASkinTB1wt

Stride: 24 bytes.

```text
0x00  SNORM16 x3  Position
0x08  SNORM8  x3  Normal
0x0c  U8      x4  Joint
0x10  S16.10  x2  TexCoord
0x14  SNORM8  x4  Tangent
```

### Layout 18: IASkinTBnwt

Stride: 28 bytes.

```text
0x00  SNORM16 x3  Position
0x08  SNORM8  x3  Normal
0x0c  SNORM8  x4  Tangent
0x10  U8      x4  Joint
0x14  UNORM8  x3  Weight; fourth weight is implicit
0x18  S16.10  x2  TexCoord
```

## MOD v7 Model Architecture

### Loader and Header

`rModel::load(MtStream&)` is at `0x1bdbaf8`.

Confirmed header:

```text
0x00  char[4]   magic = "MOD\0"
0x04  u16       version = 7
0x06  u16       bone_count
0x08  u16       primitive_count
0x0a  u16       material_name_count
0x0c  u32       vertex_count
0x10  u32       index_count field
0x14  u32       triangle_count
0x18  u32       vertex_buffer_size
0x1c  u32       reserved/flags
0x20  u32       aux20_record_count
0x24  u32       bone_palette_count
0x28  u64       bone_section_offset
0x30  u64       aux20_offset
0x38  u64       material_name_offset
0x40  u64       primitive_offset
0x48  u64       vertex_buffer_offset
0x50  u64       index_buffer_offset
0x58  u64       optional/unknown offset
0x60  float[12] model bounds and extent fields
0xa0  ...       first data section
```

`ma320900.mod`:

| Field | Value |
|---|---:|
| File size | 1,619,194 |
| Bones | 91 |
| Primitives | 75 |
| Material names | 1 |
| Vertices | 52,667 |
| Index count field | 88,136 |
| Triangles | 44,867 |
| Vertex buffer size | 1,371,932 |
| Bone palettes | 3 |

### Section Layout

| Section | Range / size |
|---|---|
| Header | `0x000000..0x0000a0` |
| Bone section | `0x0000a0..0x004714` |
| Aux20 table | `25 * 0x20` |
| Material names | `1 * 0x80` |
| Primitive table | `75 * 0x38` |
| Material/bind table | `331 * 0x90` in this sample |
| Vertex buffer | 1,371,932 bytes |
| Index buffer | 16-bit strip indices to EOF |

### Primitive Record

Primitive records are `0x38` bytes. Earlier `0x70` interpretations skipped
every second record and were incorrect.

Confirmed or strongly supported fields:

```text
0x00  u16  sentinel; observed 0xffff
0x02  u16  vertex_count
0x04  u32  packed flags; bits 12..23 are the material slot index (into the
           model's MRL material list), bits 24..31 are a per-LOD visibility
           bitmask (0x01=LOD0 highest, 0x02=LOD1, 0x0C=LOD2/LOD3 lowest). The
           exporter keeps only the primitives whose bit matches the requested
           LOD and binds each primitive to its MRL material.
0x08  u16  draw flags; observed 17
0x0a  u8   stored vertex size; observed 24 or 28
0x0b  u8   vertex class/flags; observed 4 or 68
0x0c  u32  vertex start
0x10  u32  vertex base byte offset
0x14  u32  low 12 bits are MFX input-layout ID
0x18  u32  index start
0x1c  u32  index count
0x20  u32  additional vertex start/base term
0x24  u8   bone palette index
0x25  u8   material/bind table selector, not fully named
0x26  u16  group ID
0x28  u16  vertex range start
0x2a  u16  vertex range end
0x2c  u32  flags/range field
0x30  u64  runtime pointer slot; zero on disk
```

`rModel::createVertexArrays()` at `0x1bdc3ac` proves:

- primitive `+0x14` low 12 bits index the MFX input-layout table;
- bits 44..55 of the first primitive qword select the material;
- the layout's calculated stride is used by the runtime;
- layouts 14 and 18 produce the observed 24/28-byte vertices.

### Index Topology

The sample uses 16-bit triangle strips. No `0xffff` restart markers were found
in the tested ranges; repeated indices create degenerate triangles.

After alternating strip winding and discarding degenerate triangles:

```text
faces = 44,867
```

This exactly matches the MOD header triangle count.

### Bone Section

Per bone:

```text
24-byte bone metadata record
64-byte local bind matrix
64-byte position decode / inverse-bind-related matrix
```

The parent index is byte `+0x02` of each 24-byte bone record. The root parent
is `0xff`.

The second matrix set is related to quantized position decode. For all 91
bones:

```text
decode_matrix[bone] * world_bind_matrix[bone]
```

converges to the same global matrix within a maximum element delta of about
`0.001066`:

```text
[ 3734.351318,    0.000000,    0.000000, 0 ]
[    0.000000, 3734.351318,    0.000000, 0 ]
[    0.000000,    0.000000, 3734.351318, 0 ]
[ -890.120178,   -0.119446, -271.318665, 1 ]
```

Applying SNORM16 positions through this matrix reconstructs the bind-pose
model bounds without fitting observed minima/maxima.

### Bone Palettes

The header palette count is 3. Each palette record is 36 bytes:

```text
u32  count
u8   bone_ids[32]
```

Primitive byte `+0x24` selects palette 0, 1, or 2.

The previous assumption that the preceding `0x1000` block contained palettes
was incorrect. It is a joint-usage-to-bone lookup map. Each byte maps a
12-bit animation usage ID to a MOD bone index; `0xff` means no mapping.

For `ma320900.mod`:

```text
standard usage IDs 0..84 -> 85 model bones
special usage ID 4000   -> bone 19
special usage ID 4001   -> bone 46
special usage ID 4002   -> bone 87
special usage ID 4003   -> bone 88
special usage ID 4004   -> bone 72
special usage ID 4005   -> bone 73
total valid mappings     = 91
```

Skinning validation across all 75 primitives:

| Layout | Vertices | Weight rule |
|---|---:|---|
| 14 `IASkinTB1wt` | 25,686 | `Joint.x` at weight 1.0 |
| 18 `IASkinTBnwt` | 26,981 | three explicit UNORM8 weights plus `255-sum(xyz)` |

Primitive byte `+0x24` selects the palette, and every positive local joint
reference is within that palette. Influence counts are:

```text
1 influence  = 51,164 vertices
2 influences =    285 vertices
3 influences =    682 vertices
4 influences =    536 vertices
```

The sample uses 81 of its 91 bones for vertex deformation.

### Coordinate Conversion

The OBJ exporter converts engine coordinates to Blender coordinates:

```text
blender = (engine.x, -engine.z, engine.y)
```

Blender then applies a scale of `0.01`. The corrected OBJ import explicitly
uses source forward `-Y` and source up `Z`, preventing a second axis
conversion.

## MRL v0x32 Material Architecture

`rMaterial::load(MtStream&)` at `0x1bda768` checks the first qword against:

```text
4d 52 4c 00 32 00 00 00
MRL\0 + version 0x32
```

Confirmed header fields in `ma320900.mrl`:

```text
0x00  char[4]  magic = "MRL\0"
0x04  u32      version/flags = 0x32
0x08  u32      material_count = 1
0x0c  u32      resource_count = 2
0x10  u32      observed 1
0x18  u64      resource_table_offset = 0x28
0x20  u64      material_table_offset = 0x148
```

Resource records are `0x90` bytes. The loader resolves a DTI/type ID and asks
the resource system to load the path stored at record `+0x10`.

The two sample records reference:

```text
character\ma320900\mod\ma320900_BM
character\ma320900\mod\ma320900_NM
```

The material block starts at `0x148` and contains shader hashes, parameter
records, colors, scalar values, and texture bindings. Its full semantic naming
is not complete. The current FBX uses a practical Principled material with BM
as base color and NM as a normal map.

## LMT v68 Motion Architecture

Sample:

```text
research_output\320900_first89_v2\motion\ma\ma320900\ma320900.lmt
```

Header:

```text
0x00  char[4]  magic = "LMT\0"
0x04  u16      version = 68
0x06  u16      motion_count = 39
0x08  u64[]    relative offsets to motion records
```

`rMotionList::load()` relocates:

- the top-level motion offset table;
- each motion's track-table pointer;
- each track's key-data pointer;
- an auxiliary track pointer for codecs that require one;
- four pointers in an optional motion auxiliary block.

### Motion Record

Each non-null top-level offset points to a `0x60`-byte record:

```text
0x00  u64  track_table_offset
0x08  u32  track_count
0x0c  u32  frame_count
0x10  s32  loop_frame; -1 on many non-looping clips
0x40  u32  flags
0x48  u64  auxiliary_block_offset
```

The `ma320900.lmt` sample has 39 slots, 36 non-null motions, and exactly 132
tracks in every non-null motion.

### Track Record

Each track is `0x30` bytes:

```text
0x00  u8     compression codec
0x01  u8     channel usage
0x04  s32    joint usage ID; -1 for root/global channels
0x08  f32    blend weight
0x0c  u32    key-data size or count
0x10  u64    key-data offset
0x18  f32[4] inline value / codec parameters
0x28  u64    auxiliary offset
```

`uModel::setupMotionParam()` maps nonnegative IDs through the MOD `0x1000`
lookup block before addressing a model bone. No LMT joint usage in this sample
is unmapped.

Observed channel usages:

| Value | Runtime destination | Sample track count |
|---:|---|---:|
| 0 | joint rotation | 3,060 |
| 1 | joint translation | 1,620 |
| 3 | root rotation | 36 |
| 4 | root translation | 36 |

Usages 2 and 5 exist in the runtime switch but are absent from this sample.

### Compression Codecs

`nMotion::calcMotionKey()` confirms this dispatch:

| Codec | Runtime template or behavior | Sample count |
|---:|---|---:|
| 1 | constant inline float4 | 1,080 |
| 2 | constant inline float4 | 1,466 |
| 3 | uncompressed timed float4 | 0 |
| 4 | `MPARAM_LINEARKEY_16` | 97 |
| 5 | `MPARAM_LINEARKEY_8` | 479 |
| 6 | `MPARAM_POLAR3KEY` | 883 |
| 7 | `MPARAM_POLAR3KEY_32` | 384 |
| 8 | uncompressed float3 | 0 |
| 9 | uncompressed float4 | 0 |
| 11 | `MPARAM_QUNIAXIAL_32` variant | 300 |
| 12 | `MPARAM_QUNIAXIAL_32` variant | 61 |
| 13 | `MPARAM_QUNIAXIAL_32` variant | 2 |
| 14 | `MPARAM_QUATKEY_48` | 0 |
| 15 | `MPARAM_QUATKEY_40` | 0 |

The record graph, channel mapping, and codec selection are confirmed. Exact
packed-key bit extraction and conversion to Blender F-curves remain incomplete.

Generated report:

```text
research_output\320900_lmt_inspection\ma320900_lmt_report.json
```

## Mission and Runtime Data Formats

The `mi` archive category means mission data. It is not evidence of a `.mit`
format.

Sample `mi/10000001.arc` contains:

| Magic | Extension | Role |
|---|---|---|
| `GLD\0` | `.gld` | mission path/grid data |
| `SDL\0` | `.sdl` | mission and camera scheduler |
| `XFS\0` | `.xfs` | mission FSM |
| `LCM\0` | `.lcm` | camera motion |

Observed versions:

```text
GLD  version 1
SDL  version 22
XFS  version 16
LCM  version 5
```

These formats are cataloged but not yet converted to an external editor
format.

## Effect and Audio Formats

### EFL

`rEffectList::load()` verifies:

```text
magic       = "EFL\0"
version tag = 0x20120816
```

The loader copies a resource descriptor block and resolves linked textures,
models, animations, and sub-effects.

### EAN

`rEffectAnim::load()` verifies:

```text
magic       = "EAN\0"
version tag = 0x20100924
```

The header stores a payload size and an additional count/flag before the
animation payload.

### BMB and M3R

`IBMB` and `BR3M` are Bishamon middleware resources:

```text
rBishamonBMB -> bmb
rBishamonM3R -> m3r
```

They are VFX resources rather than the main character MOD model format.

### Sound

Confirmed engine extensions include:

```text
rSoundBank       -> sbkr
rSoundRequest    -> srqr
rSoundSequenceSe -> ssqr
```

`FWSE` files are currently emitted as `.sew`. Ogg payloads use standard
`OggS` magic.

## FBX Validation

Validated static files:

```text
research_output\320900_fbx_static_phase\ma320900.fbx
research_output\320900_fbx_static_phase\ma320900_BM.png
research_output\320900_fbx_static_phase\ma320900_NM.png
research_output\320900_fbx_static_phase\ma320900_preview.png
research_output\320900_fbx_static_phase\ma320900_fbx_report.json
research_output\320900_fbx_corrected_v2\ma320900.fbx
research_output\320900_fbx_corrected_v2\ma320900_BM.png
research_output\320900_fbx_corrected_v2\ma320900_NM.png
research_output\320900_fbx_corrected_v2\ma320900_preview.png
research_output\320900_fbx_corrected_v2\ma320900_fbx_report.json
```

Source and FBX round-trip statistics:

| Metric | Source OBJ in Blender | Re-imported FBX |
|---|---:|---:|
| Meshes | 1 | 1 |
| Vertices | 52,667 | 52,667 |
| Polygons | 44,867 | 44,867 |
| Loops | 134,601 | 134,601 |
| Materials | 1 | 1 |

Round-trip bounds, in scaled Blender units:

```text
min = (-8.900418, -2.713188, -0.001195)
max = ( 8.901201,  1.870563, 28.441507)
```

The preview is upright, textured, and shows the complete model including its
long weapon. This validates static geometry, UVs, texture decode, coordinate
conversion, and FBX serialization.

The latest static-phase validation is documented separately in
`research\VALIDATION_320900.md`.

Experimental skinned files:

```text
research_output\320900_fbx_skeletal_experimental\ma320900.fbx
research_output\320900_fbx_skeletal_experimental\ma320900_BM.png
research_output\320900_fbx_skeletal_experimental\ma320900_NM.png
research_output\320900_fbx_skeletal_experimental\ma320900_preview.png
research_output\320900_fbx_skeletal_experimental\ma320900_fbx_report.json
```

The skinned source scene contains one mesh, one armature, 91 bones, one root,
91 vertex groups, and one armature modifier. The re-imported FBX preserves all
91 bones, the hierarchy, mesh counts, topology, and bounds. It retains 81
vertex groups because the FBX exporter removes the ten groups with no weighted
vertices.

The hierarchy, bind matrices, palettes, and skin weights are evidence-based.
Bone rest orientation is still marked experimental until an LMT clip is
decoded and visually validated. Neither FBX contains exact game shader
parameters.

## Tools

### ARCC extraction

```powershell
python .\tools\gbm_arc_extract.py `
  .\com.bandainamcoent.gb_jp\files\dlc\archive\ex\4127702.arc `
  -o .\research_output\4127702
```

### TEX conversion

```powershell
python .\tools\gbm_tex_to_png.py `
  .\research_output\4127702 `
  -o .\research_output\4127702_png_corrected
```

### MFX inspection

```powershell
python .\tools\gbm_mfx_inspect.py `
  .\gundam-breaker-mobile-4-01-03\assets\nativeAndroid\system\shader\ShaderPackage.mfx `
  -o .\research_output\ShaderPackage.mfx.inspect.json
```

### MOD inspection

```powershell
python .\tools\gbm_mod_inspect.py `
  .\research_output\320900_probe\character\ma320900\mod\ma320900.mod `
  -o .\research_output\320900_probe\character\ma320900\mod\ma320900.mod.inspect.json
```

### Bind-pose OBJ

```powershell
python .\tools\gbm_mod_obj_probe.py `
  .\research_output\320900_probe\character\ma320900\mod\ma320900.mod `
  --mfx .\gundam-breaker-mobile-4-01-03\assets\nativeAndroid\system\shader\ShaderPackage.mfx `
  --texture .\research_output\320900_png_corrected\ma320900_BM.png `
  -o .\research_output\320900_bind_pose_corrected\ma320900.obj `
  --manifest .\research_output\320900_bind_pose_corrected\ma320900.manifest.json
```

### FBX conversion

Run `tools\gbm_blender_convert.py` through Blender 4.2 in background mode. The
script imports the OBJ, binds BM/NM textures, exports FBX, clears the scene,
re-imports the FBX, and writes a round-trip report. Passing both `--mod` and
`--mfx` additionally creates the armature and skin weights.

For the current static extraction phase, do not pass LMT-related arguments.

### LMT inspection

```powershell
python .\tools\gbm_lmt_inspect.py `
  .\research_output\320900_first89_v2\motion\ma\ma320900\ma320900.lmt `
  --mod .\research_output\320900_first89_v2\character\ma320900\mod\ma320900.mod `
  -o .\research_output\320900_lmt_inspection\ma320900_lmt_report.json
```

## IDA Evidence Index

| Address | Symbol | Finding |
|---:|---|---|
| `0x1bb8644` | `rArchive::load` | ARC/ARCS/ARCC v8 loader |
| `0x1be6bc0` | `rTexture::load` | TEX v10 header and format selection |
| `0x1b60ef4` | `nDraw::Texture::getBufferSize` | block/bit-size calculation |
| `0x1bdc3ac` | `rModel::createVertexArrays` | MFX layout and material selection |
| `0x1bdbaf8` | `rModel::load` | MOD v7 section reader |
| `0x1bda768` | `rMaterial::load` | MRL v0x32 loader |
| `0x1ca976c` | `rShader::load` | MFX v54 loader and pointer relocation |
| `0x1bdd3f8` | `rMotionList::load` | LMT v68 loader |
| `0x1bbb598` | `nMotion::calcMotionKey` | LMT codec dispatch and key evaluation |
| `0x1dcc014` | `uModel::setupMotionParam` | track usage and MOD joint-map binding |
| `0x1bc6b78` | `rEffectList::load` | EFL loader |
| `0x1bc7d10` | `rEffectAnim::load` | EAN loader |

Key findings have also been added as comments in the active IDA database.

## Remaining Work

Priority order for the current static phase:

1. Add an end-to-end command that accepts one ARC and emits FBX plus PNGs.
2. Parse MRL shader/material parameter records and per-primitive assignments.
3. Validate the static pipeline across more character archives.
4. Build a global TOC/resource index for all 15,180 archives.
5. Resume LMT animation only after the static extraction path is generalized.

## External References

- <https://github.com/jamesu/mtmobile-tools>
- <https://github.com/jamesu/mtmobile-tools/blob/master/decryptArcTool/main.cpp>
- <https://github.com/jamesu/mtmobile-tools/blob/master/texTool/main.cpp>
- <https://gitlab.com/svanheulen/mhff/-/commit/cbb4a51250898aa57def9cffa7bf877e4bb834ac>
- <https://github.com/Zheneq/Noesis-Plugins/blob/master/fmt_mtframework_3ds_tex.py>
- <https://github.com/xZombieAlix/MT-Framework-Mobile---Blender-Model-Script>

These projects provide useful MT Framework context, but GBM-specific version,
format-ID, and layout decisions in this document are based on the local GBM
binary and samples.
