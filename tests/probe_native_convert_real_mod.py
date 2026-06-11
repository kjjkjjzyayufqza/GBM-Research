import shutil
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from gbm_native_convert import convert_mod_native  # noqa: E402


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

    output_root = Path(__file__).resolve().parents[1] / "out" / "native_probe" / "chr210100"
    if output_root.exists():
        shutil.rmtree(output_root)

    result = convert_mod_native(
        mod_path,
        output_root,
        mfx_path=TOOLS_DIR / "ShaderPackage.mfx",
        mrl_path=mrl_path,
        png_dir=png_dir,
        formats=("obj", "fbx", "glb"),
        lod=0,
    )
    for path in (result.obj, result.mtl, result.glb, result.fbx):
        assert path is not None and path.is_file(), path
        assert path.stat().st_size > 0, path
    assert result.checks["obj"]["vertices"] == result.counts["vertices"]
    assert result.checks["glb"]["triangles"] == result.counts["triangles"]
    assert result.checks["fbx"]["geometry_vertices"] == result.counts["vertices"]
    print(
        "ok native convert {mod} -> {out} vertices={vertices} triangles={triangles}".format(
            mod=mod_path,
            out=output_root,
            vertices=result.counts["vertices"],
            triangles=result.counts["triangles"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
