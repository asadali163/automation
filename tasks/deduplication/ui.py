"""Streamlit UI for the Deduplication task."""
from typing import List

import pandas as pd
import streamlit as st

from core import pipeline
from core.ui_helpers import pick_dataframe_source

from . import logic

MAX_PASSES = 10


def render() -> None:
    st.header("Deduplication")
    st.caption(
        "Continue from the Merge Files output, or upload your own CSV/Excel "
        "file. Define one or more dedup passes — passes run in order, each "
        "one dedupes the *output* of the pass before it, keeping the first "
        "occurrence within each duplicate group."
    )

    df, source_id = pick_dataframe_source("dedup")
    if df is None:
        return

    st.success(f"Loaded {len(df):,} rows x {len(df.columns)} columns.")

    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(20), use_container_width=True)

    columns = list(df.columns)
    st.subheader("Define passes")
    num_passes = st.number_input(
        "Number of passes",
        min_value=1,
        max_value=MAX_PASSES,
        value=1,
        step=1,
        key=f"dedup_num_passes_{source_id}",
    )

    passes: List[List[str]] = []
    all_valid = True
    for i in range(int(num_passes)):
        selected = st.multiselect(
            f"Pass {i + 1}: columns that define a duplicate",
            options=columns,
            key=f"dedup_pass_{i}_cols_{source_id}",
        )
        passes.append(selected)
        if not selected:
            all_valid = False

    if not all_valid:
        st.info("Select at least one column for every pass before running.")

    if st.button("Run deduplication", type="primary", disabled=not all_valid):
        _run(df, passes)


def _run(df: pd.DataFrame, passes: List[List[str]]) -> None:
    try:
        result_df, pass_results = logic.run_passes(df, passes)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Deduplication failed: {exc}")
        return

    st.subheader("Results")
    summary = pd.DataFrame(
        [
            {
                "Pass": r.pass_number,
                "Columns": ", ".join(r.columns),
                "Rows before": r.rows_before,
                "Rows after": r.rows_after,
                "Rows removed": r.rows_removed,
            }
            for r in pass_results
        ]
    )
    st.dataframe(summary, use_container_width=True, hide_index=True)
    st.success(f"Final: {len(result_df):,} rows remain (started at {len(df):,}).")

    st.download_button(
        "Download deduplicated CSV",
        data=result_df.to_csv(index=False),
        file_name="deduplicated.csv",
        mime="text/csv",
    )

    pipeline.publish(result_df, produced_by="deduplication", task_title="Deduplication")
    st.caption("This result is now available to continue straight into the next tab.")
