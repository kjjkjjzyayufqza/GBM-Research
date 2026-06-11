import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from gbm_model_mesh import decode_mesh, mesh_counts  # noqa: E402
from gbm_mod_inspect import parse_header, parse_primitive_records  # noqa: E402
from gbm_mod_obj_probe import material_index  # noqa: E402


def material_run_count(records) -> int:
    count = 0
    last = None
    for record in records:
        current = material_index(record)
        if current != last:
            count += 1
            last = current
    return count


def main() -> int:
    project_parent = Path(__file__).resolve().parents[2]
    fixture_root = (
        project_parent
        / "GBM-Research"
        / "out"
        / "_lookup_export_work"
        / "weapon"
        / "RX-78-2"
        / "210100"
    )
    mod_path = (
        fixture_root
        / "extracted"
        / "character"
        / "chr210100"
        / "mod"
        / "chr210100.mod"
    )
    mrl_path = mod_path.with_suffix(".mrl")
    png_dir = fixture_root / "models" / "png"
    if not mod_path.is_file() or not mrl_path.is_file() or not png_dir.is_dir():
        raise FileNotFoundError(
            "real MOD fixture not found; run a real lookup export for RX-78-2/210100 first"
        )

    data = mod_path.read_bytes()
    header = parse_header(mod_path, data)
    records = parse_primitive_records(data, header)
    mesh = decode_mesh(
        mod_path,
        TOOLS_DIR / "ShaderPackage.mfx",
        mrl_path=mrl_path,
        png_dir=png_dir,
        lod=None,
    )
    counts = mesh_counts(mesh)

    assert counts["vertices"] == header.vertex_count_field, counts
    assert counts["triangles"] == header.triangle_count_field, counts
    assert counts["parts"] == material_run_count(records), counts
    print(
        "ok real decode {mod} vertices={vertices} triangles={triangles} parts={parts}".format(
            mod=mod_path,
            **counts,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
