# TEX v10 Texture Format

Last updated: 2026-06-07

## Current Support

`tools\gbm_tex_to_png.py` converts the TEX files required for the current
static model pipeline. The validated sample textures are:

```text
research_output\320900_first89_v2\character\ma320900\mod\ma320900_BM.tex
research_output\320900_first89_v2\character\ma320900\mod\ma320900_NM.tex
```

Converted PNG output:

```text
research_output\320900_png_corrected\ma320900_BM.png
research_output\320900_png_corrected\ma320900_NM.png
```

## Header Interpretation

Observed v10 fields:

```text
0x00  char[4]  "TEX "
0x04  u16      version, observed 10
0x06  u16      format code
0x08  u16      width
0x0a  u16      height-related field or flags in some samples
0x0c  u16      width in current decoded samples
0x0e  u16      packed height/flags
0x10  u32[4]   mip/data offsets or related offsets
0x20  u32[3]   reserved/optional offsets in current samples
0x2c  u32      payload size
0x30  bytes    texture payload
```

For the observed ETC2 texture samples:

```text
height = (packed_height & 0x03ff) << 3
```

## Pixel Formats

Confirmed or implemented formats:

| Format code | Meaning | Status |
|---:|---|---|
| `0x01` | RGBA8888 | implemented |
| `0x07` | RGBA4444 | implemented |
| `0x14` | ETC2 RGB8 | validated on BM texture |
| `0x15` | ETC2 RGBA8 EAC | implemented for alpha-capable ETC2 |

The ETC2 decoder path uses `texture2ddecoder`, which returns BGRA bytes. The
converter swaps red and blue before writing RGBA PNGs.

## Notes

The current pipeline uses the largest decoded image level for FBX material
binding. Full mipmap export is not required for the static FBX deliverable.
