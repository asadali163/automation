from pathlib import Path

import pytest

from core.io import read_table


def test_read_csv_keeps_blanks_as_empty_string(tmp_path: Path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("a,b\n1,\n,2\n")

    df = read_table(csv_path)

    assert list(df.columns) == ["a", "b"]
    assert df.iloc[0]["b"] == ""
    assert df.iloc[1]["a"] == ""


def test_read_table_rejects_unsupported_extension(tmp_path: Path):
    bad_path = tmp_path / "sample.txt"
    bad_path.write_text("hello")

    with pytest.raises(ValueError, match="Unsupported file type"):
        read_table(bad_path)
