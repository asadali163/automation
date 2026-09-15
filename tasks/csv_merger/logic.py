"""Pure logic for the Merge CSVs task — no Streamlit here.

This task's job is: let the user drop columns per file (to line up
mismatched schemas before merging), then combine the (already-loaded,
trimmed) DataFrames into one. The actual combine/render logic lives in
`core.table_merge`, shared with the (zip-based) Merge Files task.
"""
from typing import Dict, List, Tuple

import pandas as pd

from core.table_merge import combine_dataframes, to_marker_text  # noqa: F401 - re-exported


def drop_columns(df: pd.DataFrame, columns_to_remove: List[str]) -> pd.DataFrame:
    """Return `df` with `columns_to_remove` dropped. Any name not actually
    present in `df` is silently ignored.
    """
    existing = [c for c in columns_to_remove if c in df.columns]
    return df.drop(columns=existing) if existing else df


def merge_csvs(labeled_dfs: List[Tuple[str, pd.DataFrame]]) -> Tuple[pd.DataFrame, Dict]:
    """Combine (label, df) pairs — already loaded and column-trimmed — into
    one table tagged with a `source_file` column.
    """
    combined = combine_dataframes(labeled_dfs)
    stats = {
        "files_merged": len(labeled_dfs),
        "total_rows": len(combined),
    }
    return combined, stats
