# IDA Evidence Index

Last updated: 2026-06-07

These addresses are anchors in `libGUNS.so` used to confirm format behavior.

| Address | Symbol / area | Finding |
|---:|---|---|
| `0x1be6bc0` | `rTexture::load` | TEX v10 loader and format dispatch |
| `0x1bdbaf8` | `rModel::load` | MOD v7 loader and section relocation |
| `0x1bda768` | `rMaterial::load` | MRL loader and version check |
| `0x1ca976c` | `rShader::load` | MFX v54 loader and pointer relocation |
| `0x1bdd3f8` | `rMotionList::load` | LMT v68 loader |
| `0x1dcc014` | `uModel::setupMotionParam` | LMT track usage and MOD joint-map binding |
| `0x1bbb598` | `nMotion::calcMotionKey` | LMT codec dispatch |
| `0x1bc6b78` | `rEffectList::load` | EFL loader |
| `0x1bc7d10` | `rEffectAnim::load` | EAN loader |

## Current Use

The static extraction path depends mainly on the TEX, MOD, MRL, and MFX loader
evidence. LMT evidence is recorded but not used by the current deliverable.

## Evidence Level

Use these levels when updating research notes:

| Level | Meaning |
|---|---|
| Confirmed | Native evidence and successful local extraction or conversion agree |
| Working hypothesis | Local evidence is consistent but not fully generalized |
| Open | Format is observed but not needed or not yet decoded |
