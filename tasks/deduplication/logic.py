"""Pure logic for the Deduplication task — no Streamlit here, so it's easy
to unit test and reuse elsewhere.

Passes are CASCADING: pass N runs on the OUTPUT of pass N-1 (pass 1 runs on
the original data), and each pass keeps the first occurrence within every
duplicate group defined by that pass's chosen columns.
"""
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd


@dataclass(frozen=True)
class PassResult:
    pass_number: int
    columns: List[str]
    rows_before: int
    rows_after: int
    rows_removed: int


def run_passes(df: pd.DataFrame, passes: List[List[str]]) -> Tuple[pd.DataFrame, List[PassResult]]:
    """Run each pass's dedup in order, cascading, and return the final
    DataFrame plus a per-pass before/after row-count report.
    """
    if not passes:
        raise ValueError("At least one pass is required.")

    current = df
    results: List[PassResult] = []

    for i, cols in enumerate(passes, start=1):
        if not cols:
            raise ValueError(f"Pass {i} has no columns selected.")
        missing = [c for c in cols if c not in current.columns]
        if missing:
            raise ValueError(f"Pass {i}: unknown column(s) {missing}")

        before = len(current)
        deduped = current.drop_duplicates(subset=cols, keep="first")
        after = len(deduped)
        results.append(PassResult(i, list(cols), before, after, before - after))
        current = deduped

    return current.reset_index(drop=True), results
