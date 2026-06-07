# LMT Animation Research Deferred

Last updated: 2026-06-07

## Scope Decision

LMT animation is not part of the current extraction milestone. The immediate
goal is static model and texture output from game files.

The working deliverable does not require:

- animation curves;
- Blender actions;
- skeleton retargeting;
- runtime root motion;
- exact game pose playback.

## What Is Known

The sample motion file is:

```text
research_output\320900_first89_v2\motion\ma\ma320900\ma320900.lmt
```

Observed structure:

```text
magic       = "LMT\0"
version     = 68
motion slots = 39
non-null motions = 36
track record size = 0x30
```

Runtime evidence maps LMT joint usage IDs through the MOD 0x1000 joint-usage
map before addressing bones.

## Current Warning

A dynamic motion experiment exported an FBX action but did not pass visual
validation: the tested pose left the preview frame and produced abnormal bounds.
Therefore dynamic LMT-to-FBX output should be treated as experimental and
excluded from the current pipeline.

The earlier constant-pose experiment was useful for research context, but it is
also outside the static extraction deliverable.

## When To Resume

Resume LMT work only after the static pipeline has:

1. a single end-to-end wrapper;
2. validation across several character archives;
3. clearer MRL material mapping.
