# GBM Resource Format Catalog

Last updated: 2026-06-07

This catalog lists formats observed in extracted GBM resources or confirmed by
native loader evidence. The current extraction phase only needs ARCC, TEX, MOD,
MRL, and MFX.

Related docs:

- [README.md](README.md) - project entry point and key document index.
- [RESOURCE_NAME_MAPPING.md](RESOURCE_NAME_MAPPING.md) - maps human-facing unit names to `ch/*.arc` model archives.
- [TOOLS_REFERENCE.md](TOOLS_REFERENCE.md) - command-oriented reference for extraction tools.

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

## DLC Archive Directories

Last sampled: 2026-06-11

The DLC archive root is:

```text
com.bandainamcoent.gb_jp/files/dlc/archive/
```

The table below is based on a full TOC scan of all 15,180 `.arc` files in that
directory. It reads decrypted archive tables only; payloads are not extracted
for this classification.

| Directory | ARC count | Current interpretation | Main internal evidence |
|---|---:|---|---|
| `ch` | 3162 | Character/mobile-suit primary packages | `character/.../mod`, `motion/ms`, `vfx`, `sound` |
| `ma` | 86 | Stage/map visual packages | `stage/m100...`, `stage/m800...`, stage textures/models, VFX, scheduler |
| `mi` | 3967 | Mission logic packages | `scheduler/mission`, `fsm/mission`, `motion/camera`, `scheduler/camera` |
| `pmi` | 1100 | Mission logic packages, alternate set | Same pattern as `mi`: mission scheduler/FSM/camera resources |
| `we` | 1901 | Weapon presentation packages | `sound/se/weapon`, `vfx`, `shell/hit`, `shell/beam`, `shell/shot` |
| `ex` | 2867 | EX-skill / skill-effect packages | `vfx/texture`, `vfx/bmb`, `vfx/efl`, `shell/sk`, `sound/se` |
| `sps` | 795 | Special/common mobile-suit motion packages | Almost entirely `motion/ms/.../sps_*` resources |
| `st` | 259 | Story/skit script packages | `message/skit/script/...` |
| `ra` | 130 | ADV/skit image resources | `gui/common/character/tex/ADV/...`, `gui/skit/tex/...` |
| `sc` | 7 | Character image texture sets | `gui/common/character/tex/99/...` |
| `pe` | 427 | Pilot/player character voice and portrait packages | `sound/se/voice/...`, `gui/common/character/tex/99/...` |
| `bo` | 396 | Box-art image packages | `gui/common/boxart/tex/ba_*` |
| `co` | 55 | Common/global resource packages | GUI config, common textures, sound request tables, loading/tutorial/photo-studio assets |
| `ar` | 28 | Arena/task-stage packages | `scheduler/arena`, `fsm/mission`, `stage/...`, `motion/camera` |

Notes:

- `ch` is not a pure model folder. A `ch/*.arc` can contain character model
  resources, motion, VFX, shell data, and sound.
- `ma` is map/stage-oriented, but map packages can also include scheduler and
  VFX resources.
- `mi` and `pmi` are mission-data packages, not model packages. The exact
  expansion of the `pmi` prefix is still unresolved.
- `we` is weapon *presentation* (effects, shell data, sound), keyed by
  `parts_id` (`we/<parts_id>.arc`). It does **not** hold the weapon mesh.
- Weapon and shield *meshes* live in `ch/`, in a separate id range addressed by
  prefixing the equip-table `model_id` with `2`: `ch/2<model_id>.arc` ->
  `character/chr2<model_id>/mod/chr2<model_id>.mod` (model_id `10100` ->
  `ch/210100.arc` -> `chr210100.mod`, a beam rifle; ~1682 `ch/2*.arc` archives).
  Do not use `ch/<model_id>.arc` for weapons — that is the suit-body archive of
  an unrelated unit. See RESOURCE_NAME_MAPPING.md.
- `ra`, `sc`, `pe`, and `ar` have clear content patterns from TOC paths, but
  the exact original abbreviation meanings remain unconfirmed.

## MIT vs LMT

No `.mit` file, `MIT\0` magic, or matching native loader has been found in the
workspace. The character motion format observed in the sample is `LMT\0`.

If a real `.mit` sample appears later, it should be documented separately. For
now, "MIT" should be treated as a likely transcription error for LMT in this
project context.
