"""Shared file-reading helpers for any task that works with tabular data
(CSV/Excel). Used by both the Merge Files and Deduplication tasks.
"""
from pathlib import Path

import pandas as pd

TABLE_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def read_table(path: Path) -> pd.DataFrame:
    """Read a .csv/.xlsx/.xls file into a DataFrame with every cell as a
    string (and blanks kept as "" rather than NaN), so equality / dedup /
    merge comparisons are exact and don't trip over numeric-dtype or
    NaN-vs-empty-string quirks.
    """
    suffix = path.suffix.lower()
    if suffix not in TABLE_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.read_excel(path, dtype=str, keep_default_na=False)
