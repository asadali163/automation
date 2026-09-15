"""Shared logic for combining multiple tabular files (CSV/Excel) into one
DataFrame with a `source_file` column, plus rendering that combined table
back into a human-readable, per-file-annotated CSV.

Used by every task that merges several files into one table — currently
Merge Files (zip upload) and Merge CSVs (direct multi-file upload). Each
task is only responsible for turning its own input (a zip's contents, a
batch of uploads, ...) into a list of `SourceFile` entries; the actual
combine/render logic lives here once, so it behaves identically everywhere.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from core.io import read_table


@dataclass(frozen=True)
class SourceFile:
    path: Path       # absolute path on disk
    rel_path: str     # label used as the source, e.g. "sub/file.csv" or just "file.csv"


def combine_dataframes(labeled_dfs: List[Tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    """Concatenate already-loaded (label, DataFrame) pairs into one
    DataFrame (rows kept in the given order; columns unioned if they
    differ), tagging each row's origin via a `source_file` column.

    Use this when the caller has already read/edited the DataFrames itself
    (e.g. after letting the user drop columns first); use `combine_tables`
    when you just have file paths to read fresh.
    """
    frames = []
    for label, df in labeled_dfs:
        df = df.copy()
        df.insert(0, "source_file", label)
        frames.append(df)

    return (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else pd.DataFrame(columns=["source_file"])
    )


def combine_tables(files: List[SourceFile]) -> Tuple[pd.DataFrame, Dict]:
    """Read every file into one combined DataFrame (rows kept in the given
    order; columns unioned if files differ), tagging each row's origin via
    a `source_file` column.

    This combined table is what downstream tasks (e.g. Deduplication)
    consume when you continue the pipeline instead of re-uploading. Use
    `to_marker_text()` to render the human-readable, per-file-annotated
    version for download.
    """
    labeled_dfs = []
    errors = []

    for f in files:
        try:
            df = read_table(f.path)
        except Exception as exc:  # noqa: BLE001 - surface any read failure per-file
            errors.append(f"{f.rel_path}: {exc}")
            continue
        labeled_dfs.append((f.rel_path, df))

    combined = combine_dataframes(labeled_dfs)
    stats = {
        "files_found": len(files),
        "files_merged": len(files) - len(errors),
        "total_rows": len(combined),
        "errors": errors,
    }
    return combined, stats


def to_marker_text(combined: pd.DataFrame) -> str:
    """Render a combined DataFrame (as produced by `combine_tables`) into
    the human-readable download format: one block per source file, each
    preceded by a `--- Source: <rel_path> ---` marker line.
    """
    if combined.empty:
        return ""
    blocks = []
    for source in combined["source_file"].unique():  # preserves first-seen order
        block_df = combined.loc[combined["source_file"] == source].drop(columns=["source_file"])
        blocks.append(f"--- Source: {source} ---\n{block_df.to_csv(index=False)}")
    return "\n".join(blocks)
