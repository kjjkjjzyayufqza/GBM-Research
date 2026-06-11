# Resource Name Mapping

Last updated: 2026-06-07

GBM does have a local list-like mapping, but it is not a friendly text file in
the DLC `archive/ch` directory. The useful mapping lives in the APK-side
native tables:

Related docs:

- [README.md](README.md) - project entry point and key document index.
- [RESOURCE_FORMAT_CATALOG.md#dlc-archive-directories](RESOURCE_FORMAT_CATALOG.md#dlc-archive-directories) - meaning of `archive/ch`, `archive/ma`, `archive/we`, and other DLC folders.
- [TOOLS_REFERENCE.md#toolsgbm_equip_lookuppy](TOOLS_REFERENCE.md#toolsgbm_equip_lookuppy) - command reference for regenerating lookup CSVs.

```text
gundam-breaker-mobile-4-01-03/assets/nativeAndroid/tuning/equip/
  table_head.eth
  table_body.etb
  table_arms.eta
  table_leg.etl
  table_backpack.etbp
  table_short_weapon.etws
  table_long_weapon.etwl
  table_shield.ets
```

These are XFS-style binary property tables. They contain field names such as:

```text
parts_id
parts_name_id
gunpla_id
model_id
parts_type
serial_name
```

For asset extraction, the important chain is:

```text
serial_name / unit code
  -> equip table row
  -> model_id
  -> com.bandainamcoent.gb_jp/files/dlc/archive/ch/<model_id>.arc
  -> character/<internal stem>/mod/*.mod, *.mrl, *.tex
```

The `ch` archive file name is numeric because it is keyed by `model_id`, not by
the human-facing unit name.

For the broader meaning of DLC archive directories such as `ch`, `ma`, `mi`,
`we`, and `ex`, see [RESOURCE_FORMAT_CATALOG.md](RESOURCE_FORMAT_CATALOG.md#dlc-archive-directories).

## Lookup CSVs

Start with the CSV files in `tools/`:

```text
tools/gbm_archive_lookup_index.csv
tools/gbm_equip_parts_index.csv
tools/gbm_weapon_parts_index.csv
```

`gbm_archive_lookup_index.csv` is the human-readable first stop for mobile suit
body resources. It is generated from the head/body/arms/legs/backpack equip
tables only, so weapon and shield model archives do not get folded into a
unit's body archive list. It has one row per `serial_name + gunpla_id +
model_id` and keeps the common lookup fields:

```text
serial_name, gunpla_id, model_id, part_types, parts_count,
primary_ch_archive, has_ch_archive, ch_archives, source_tables
```

`gbm_equip_parts_index.csv` is the matching body-part-level index. It has one
row per detected head/body/arms/legs/backpack equip table part record:

```text
serial_name, gunpla_id, model_id, part_type, parts_id, parts_name_id,
table_file, has_ch_archive, ch_archives
```

`gbm_weapon_parts_index.csv` is the matching weapon/shield part-level index. It
is generated from `table_long_weapon.etwl`, `table_short_weapon.etws`, and
`table_shield.ets`. It is ordered by source table and original record offset,
not alphabetically by `serial_name`.

### Weapon and shield meshes live in `ch/2<model_id>.arc`

> A weapon/shield `model_id` is a **separate id space** from the suit-body
> model_id. The mesh archive is addressed by prefixing the table `model_id`
> with `2`:
>
> ```text
> weapon table row -> model_id (e.g. 10100)
>   -> ch/2<model_id>.arc        (ch/210100.arc)
>   -> character/chr2<model_id>/mod/chr2<model_id>.mod  (chr210100.mod)
> ```
>
> RX-78-2 beam rifle `model_id 10100` -> `ch/210100.arc` ->
> `chr210100.mod` (4 bones, material `MaterialSkinChr_GUNS__2`; a `__N` slot
> material, not a body `__HEAD/__BODY/...` material). Other examples:
> `10600` -> `ch/210600.arc` (hyper bazooka), `12100` -> `ch/212100.arc`
> (shield), `11100` -> `ch/211100.arc` (beam saber), and the 9xxxx variants
> work too (`90600` -> `ch/290600.arc`).
>
> **Do NOT use `ch/<model_id>.arc` directly for weapons** — that is the body
> rule and resolves to an unrelated suit whose body happens to share the number
> (`ch/10100.arc` = RX-178 / Gundam Mk-II). Each weapon archive also carries a
> `chr2<model_id>_dummy.mod` (a low-LOD/placeholder variant).
>
> `we/<parts_id>.arc` is a **separate** package holding the weapon's
> effect/shell/sound presentation (beam, muzzle, hit vfx) — not the mesh.
>
> `gbm_equip_lookup.py` resolves weapon rows through `weapon_mesh_model_id()`
> (the `2`-prefix), so `gbm_weapon_parts_index.csv` `ch_archives` points at the
> real weapon mesh, and `gbm_export_weapons_obj.py` / `gbm_export_weapons_fbx.py`
> export the correct weapon model.

For a normal human lookup, open `gbm_archive_lookup_index.csv` and filter
`serial_name`.

The body CSV files keep the source unit ordering from `table_body.etb`; they
are not alphabetically sorted by `serial_name`. Rows that do not have a
matching body-table unit fall back to numeric/source-table order.

## Lookup Tool

The Python lookup tool remains useful when regenerating or filtering from the
raw APK tables, but the CSVs above should be read first.

Regenerate the CSVs with:

```powershell
python .\tools\gbm_equip_lookup.py --write-indexes
```

Pass `--include-non-suit-parts` only when you intentionally want weapon and
shield rows included in the generated indexes.

Use:

```powershell
python .\tools\gbm_equip_lookup.py RX-78-2 --exact
```

Useful variants:

```powershell
python .\tools\gbm_equip_lookup.py RX-78
python .\tools\gbm_equip_lookup.py RX-78-2 --exact --gunpla-id 10000
python .\tools\gbm_equip_lookup.py "Gundam Artemis"
python .\tools\gbm_equip_lookup.py RX-78-2 --exact --json
```

The tool scans the equip tables and reports:

- `serial_name`
- part type
- `gunpla_id`
- `model_id`
- `parts_id`
- table file
- matching `archive/ch` variants present in the current DLC dump

It is a targeted parser for the validated equip table row layout. It is not a
full generic XFS parser.

## RX-78-2 Result

The base RX-78-2 body parts map to `model_id = 10000`:

| Part group | `model_id` | Current archive variants |
|---|---:|---|
| Head, body, arms, legs, backpack | `10000` | `ch/10000.arc`, `ch/10000_vfx.arc` |

So the RX-78-2 archive to inspect for the main mobile suit body is:

```text
com.bandainamcoent.gb_jp/files/dlc/archive/ch/10000.arc
```

Its ARC table contains internal resources such as:

```text
character/chr100009/mod/chr100000_P00_BM
character/chr100009/mod/chr100000_NM
character/chr100009/mod/chr100000
character/chr100009/mod/chr100009
```

The extractor infers final extensions from decoded magic, so those extensionless
entries become `.tex`, `.mrl`, `.mod`, and related files during extraction.

## Practical Commands

List the RX-78-2 main archive:

```powershell
python .\tools\gbm_arc_extract.py `
  ..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\10000.arc `
  --list-only
```

Extract it:

```powershell
python .\tools\gbm_arc_extract.py `
  ..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\10000.arc `
  -o .\out\rx-78-2\extracted
```

The likely full combined model stem in `ch/10000.arc` is `chr100009`.
Individual part stems such as `chr100000`, `chr100001`, `chr100002`,
`chr100003`, and `chr100004` are also present.

Run the static pipeline against the combined stem:

```powershell
python .\tools\gbm_start.py `
  ..\com.bandainamcoent.gb_jp\files\dlc\archive\ch\10000.arc `
  --model-stem chr100009 `
  -o .\out\rx-78-2 `
  --skip-fbx `
  --force
```

Add FBX output by omitting `--skip-fbx` when Blender is available.
