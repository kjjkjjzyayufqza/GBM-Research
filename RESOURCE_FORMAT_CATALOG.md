# GBM Resource Format Catalog

Last updated: 2026-06-07

This catalog lists formats observed in extracted GBM resources or confirmed by
native loader evidence. The current extraction phase only needs ARCC, TEX, MOD,
MRL, and MFX.

| Magic | Extension | Role | Current support |
|---|---|---|---|
| `ARCC` | `.arc` | DLC archive container | extracted |
| `TEX ` | `.tex` | texture resource | PNG conversion for observed formats |
| `MOD\0` | `.mod` | model geometry and skeleton data | bind-pose OBJ export |
| `MRL\0` | `.mrl` | material resource list | paths and references inspected |
| `MFX\0` | `.mfx` | shader package and input layouts | input layouts parsed |
| `LMT\0` | `.lmt` | motion list | deferred |
| `LCM\0` | `.lcm` | camera list | catalog only |
| `SDL\0` | `.sdl` | scheduler data | catalog only |
| `GLD\0` | `.gld` | mission/grid data | catalog only |
| `IBMB` | `.bmb` | Bishamon effect package | catalog only |
| `EAN\0` | `.ean` | effect animation | catalog only |
| `EFL\0` | `.efl` | effect list | catalog only |
| `BR3M` | `.m3r` | Bishamon effect-related resource | catalog only |
| `FWSE` | `.sew` | sound effect wrapper | catalog only |
| `OggS` | `.ogg` | audio stream | extension inference only |
| `XFS\0` | `.xfs` | model-adjacent resource | catalog only |
| `geo3` | `.geo3` | model-adjacent resource | catalog only |
| `GMD\0` | `.gmd` | message or game data | catalog only |
| `GUI\0` | `.gui` | UI resource | catalog only |
| `GFD\0` | `.gfd` | UI/font or graphics data | catalog only |
| `PRPZ` | `.prp` | property data | catalog only |
| `SBKR` | `.sbkr` | sound bank related | catalog only |
| `SRQR` | `.srqr` | sound request related | catalog only |
| `SSQR` | `.ssqr` | sound sequence related | catalog only |

## MIT vs LMT

No `.mit` file, `MIT\0` magic, or matching native loader has been found in the
workspace. The character motion format observed in the sample is `LMT\0`.

If a real `.mit` sample appears later, it should be documented separately. For
now, "MIT" should be treated as a likely transcription error for LMT in this
project context.
