import pandas as pd

from tasks.csv_merger import logic


def test_drop_columns_removes_only_requested_and_present_columns():
    df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})

    result = logic.drop_columns(df, ["b", "not_a_column"])

    assert list(result.columns) == ["a", "c"]


def test_drop_columns_no_op_when_nothing_selected():
    df = pd.DataFrame({"a": [1], "b": [2]})

    result = logic.drop_columns(df, [])

    assert list(result.columns) == ["a", "b"]


def test_merge_csvs_combines_labeled_dataframes_and_matches_after_drop():
    # jan has an extra "notes" column; drop it so both files line up before merging
    jan = pd.DataFrame({"name": ["Cafe A"], "city": ["Amsterdam"], "notes": ["x"]})
    feb = pd.DataFrame({"name": ["Cafe B", "Cafe C"], "city": ["Rotterdam", "Utrecht"]})

    jan_trimmed = logic.drop_columns(jan, ["notes"])
    combined, stats = logic.merge_csvs([("shops_jan.csv", jan_trimmed), ("shops_feb.csv", feb)])

    assert stats["files_merged"] == 2
    assert stats["total_rows"] == 3
    assert list(combined.columns) == ["source_file", "name", "city"]

    text = logic.to_marker_text(combined)
    assert "--- Source: shops_jan.csv ---" in text
    assert "--- Source: shops_feb.csv ---" in text
