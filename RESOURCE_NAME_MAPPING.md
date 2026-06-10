# Resource Name Mapping

Last updated: 2026-06-07

GBM does have a local list-like mapping, but it is not a friendly text file in
the DLC `archive/ch` directory. The useful mapping lives in the APK-side
native tables:

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

## Lookup CSVs

Start with the CSV files in `tools/`:

```text
tools/gbm_archive_lookup_index.csv
tools/gbm_equip_parts_index.csv
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

For a normal human lookup, open `gbm_archive_lookup_index.csv` and filter
`serial_name`.

Both CSV files keep the source unit ordering from `table_body.etb`; they are
not alphabetically sorted by `serial_name`. Rows that do not have a matching
body-table unit fall back to their source table order.

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
