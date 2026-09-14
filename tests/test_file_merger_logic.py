import zipfile
from pathlib import Path

from tasks.file_merger import logic


def _make_zip_with_nested_csvs(tmp_path: Path) -> Path:
    """sample.zip
       ├── a.csv
       └── sub/
           └── deeper/
               └── b.csv
    """
    src = tmp_path / "src"
    (src / "sub" / "deeper").mkdir(parents=True)
    (src / "a.csv").write_text("col1,col2\n1,2\n")
    (src / "sub" / "deeper" / "b.csv").write_text("col1,col2\n3,4\n5,6\n")

    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src))
    return zip_path


def test_extract_discover_merge_roundtrip(tmp_path):
    zip_path = _make_zip_with_nested_csvs(tmp_path)
    extract_dir = tmp_path / "extracted"

    logic.extract_zip(zip_path, extract_dir)
    discovered = logic.discover_files(extract_dir)

    rel_paths = sorted(f.rel_path for f in discovered)
    assert rel_paths == ["a.csv", "sub/deeper/b.csv"]

    combined_df, stats = logic.merge_files(discovered)

    assert stats["files_found"] == 2
    assert stats["files_merged"] == 2
    assert stats["total_rows"] == 3  # 1 row from a.csv + 2 rows from b.csv
    assert not stats["errors"]

    # combined_df is what downstream tasks (e.g. Deduplication) consume
    assert list(combined_df.columns) == ["source_file", "col1", "col2"]
    assert sorted(combined_df["source_file"].unique()) == ["a.csv", "sub/deeper/b.csv"]
    assert len(combined_df) == 3

    merged_text = logic.to_marker_text(combined_df)
    assert "--- Source: a.csv ---" in merged_text
    assert "--- Source: sub/deeper/b.csv ---" in merged_text


def test_discover_files_ignores_hidden_and_lock_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.csv").write_text("a\n1\n")
    (root / "~$locked.xlsx").write_text("junk")
    (root / ".hidden.csv").write_text("junk")

    discovered = logic.discover_files(root)

    assert [f.rel_path for f in discovered] == ["real.csv"]
