import pandas as pd
import pytest

from tasks.deduplication import logic


def _sample_df() -> pd.DataFrame:
    # rows 0 and 2 share colA/colB -> pass 1 (on colA,colB) should drop row 2
    # after pass 1, rows 0,1,3 remain; rows 0 and 3 then share colC -> pass 2 drops row 3
    return pd.DataFrame(
        {
            "colA": ["x", "y", "x", "x"],
            "colB": ["1", "2", "1", "9"],
            "colC": ["same", "diff1", "same-unused", "same"],
        }
    )


def test_cascading_passes_narrow_progressively():
    df = _sample_df()
    result, results = logic.run_passes(df, [["colA", "colB"], ["colC"]])

    assert [r.pass_number for r in results] == [1, 2]

    # pass 1: dedup on colA+colB -> drops row index 2 (dup of row 0)
    assert results[0].rows_before == 4
    assert results[0].rows_after == 3
    assert results[0].rows_removed == 1

    # pass 2 runs on pass 1's output (rows 0,1,3): colC values are
    # "same", "diff1", "same" -> drops row 3 (dup of row 0 on colC)
    assert results[1].rows_before == 3
    assert results[1].rows_after == 2
    assert results[1].rows_removed == 1

    assert len(result) == 2
    assert list(result["colA"]) == ["x", "y"]


def test_single_pass_keeps_first_occurrence():
    df = _sample_df()
    result, results = logic.run_passes(df, [["colA", "colB"]])

    assert len(results) == 1
    assert len(result) == 3
    # first occurrence of colA=x,colB=1 (index 0) is kept, index 2 dropped
    assert list(result["colC"]) == ["same", "diff1", "same"]


def test_unknown_column_raises():
    df = _sample_df()
    with pytest.raises(ValueError, match="unknown column"):
        logic.run_passes(df, [["not_a_column"]])


def test_empty_pass_columns_raises():
    df = _sample_df()
    with pytest.raises(ValueError, match="no columns selected"):
        logic.run_passes(df, [[]])


def test_no_passes_raises():
    df = _sample_df()
    with pytest.raises(ValueError, match="At least one pass"):
        logic.run_passes(df, [])
