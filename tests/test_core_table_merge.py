from pathlib import Path

import pandas as pd

from core.table_merge import SourceFile, combine_dataframes, combine_tables, to_marker_text


def test_combine_dataframes_tags_rows_with_source_and_unions_columns():
    a = pd.DataFrame({"col1": [1], "col2": [2]})
    b = pd.DataFrame({"col1": [3, 5], "col3": [4, 6]})  # different schema than a

    combined = combine_dataframes([("a.csv", a), ("b.csv", b)])

    assert list(combined.columns) == ["source_file", "col1", "col2", "col3"]
    assert list(combined["source_file"]) == ["a.csv", "b.csv", "b.csv"]
    assert len(combined) == 3


def test_combine_dataframes_empty_input_returns_empty_dataframe():
    combined = combine_dataframes([])
    assert list(combined.columns) == ["source_file"]
    assert combined.empty


def test_combine_tables_tags_rows_with_source_and_unions_columns(tmp_path: Path):
    a = tmp_path / "a.csv"
    a.write_text("col1,col2\n1,2\n")
    b = tmp_path / "b.csv"
    b.write_text("col1,col3\n3,4\n5,6\n")  # different schema than a.csv

    files = [
        SourceFile(path=a, rel_path="a.csv"),
        SourceFile(path=b, rel_path="b.csv"),
    ]
    combined, stats = combine_tables(files)

    assert stats == {"files_found": 2, "files_merged": 2, "total_rows": 3, "errors": []}
    assert list(combined.columns) == ["source_file", "col1", "col2", "col3"]
    assert list(combined["source_file"]) == ["a.csv", "b.csv", "b.csv"]


def test_combine_tables_reports_unreadable_file_as_error(tmp_path: Path):
    good = tmp_path / "good.csv"
    good.write_text("col1\n1\n")
    bad = tmp_path / "bad.csv"  # never written -> read_table will fail

    files = [SourceFile(path=good, rel_path="good.csv"), SourceFile(path=bad, rel_path="bad.csv")]
    combined, stats = combine_tables(files)

    assert stats["files_found"] == 2
    assert stats["files_merged"] == 1
    assert len(stats["errors"]) == 1
    assert "bad.csv" in stats["errors"][0]
    assert len(combined) == 1


def test_to_marker_text_renders_one_block_per_source_in_first_seen_order():
    combined = pd.DataFrame(
        {
            "source_file": ["b.csv", "b.csv", "a.csv"],
            "col1": ["3", "5", "1"],
        }
    )
    text = to_marker_text(combined)

    assert text.index("--- Source: b.csv ---") < text.index("--- Source: a.csv ---")
    assert "source_file" not in text.split("\n")[1]  # column dropped from each block


def test_to_marker_text_empty_dataframe_returns_empty_string():
    assert to_marker_text(pd.DataFrame(columns=["source_file"])) == ""
