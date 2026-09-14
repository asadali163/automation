"""Streamlit UI helpers shared by tasks that consume a tabular dataset.

`pick_dataframe_source` is the key piece: it lets a task offer "continue
from the previous task's output" (via `core.pipeline`) instead of forcing
a fresh upload every time, while still supporting a plain upload when you
want to start fresh.
"""
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from config import UPLOADS_DIR
from core import pipeline
from core.io import read_table
from core.utils import new_session_dir


def load_table_upload(
    key_prefix: str, label: str = "Upload a .csv or .xlsx/.xls file"
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """A file_uploader for a single CSV/Excel file, cached in session_state
    keyed by (name, size) so a rerun doesn't re-parse the file.

    Returns (dataframe, source_id) — source_id is a stable string identity
    for the current data (changes only when the uploaded file changes),
    handy as a Streamlit widget-key suffix so downstream selections reset
    correctly when the data changes. Returns (None, None) if nothing is
    uploaded yet.
    """
    uploaded = st.file_uploader(label, type=["csv", "xlsx", "xls"], key=f"{key_prefix}_upload")
    if uploaded is None:
        st.session_state.pop(f"{key_prefix}_uploaded_df", None)
        st.session_state.pop(f"{key_prefix}_uploaded_id", None)
        return None, None

    file_id = f"{uploaded.name}_{uploaded.size}"
    if st.session_state.get(f"{key_prefix}_uploaded_id") != file_id:
        session_dir = new_session_dir(UPLOADS_DIR)
        file_path = session_dir / f"input{Path(uploaded.name).suffix.lower()}"
        file_path.write_bytes(uploaded.getvalue())
        try:
            df = read_table(file_path)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not read file: {exc}")
            return None, None
        st.session_state[f"{key_prefix}_uploaded_df"] = df
        st.session_state[f"{key_prefix}_uploaded_id"] = file_id

    return st.session_state[f"{key_prefix}_uploaded_df"], file_id


def pick_dataframe_source(
    key_prefix: str, upload_label: str = "Upload a .csv or .xlsx/.xls file"
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Offers "continue from the previous task's output" (when one exists)
    alongside a plain file upload. Returns (dataframe, source_id) — see
    `load_table_upload` for what source_id is for. (None, None) if nothing
    is selected/uploaded yet.
    """
    shared = pipeline.get()
    if shared is None:
        return load_table_upload(key_prefix, upload_label)

    choice = st.radio(
        "Data source",
        [f"Continue from {shared.label}", "Upload a different file"],
        key=f"{key_prefix}_source_choice",
        horizontal=True,
    )
    if choice.startswith("Continue"):
        return shared.df, f"pipeline_{shared.produced_by}_{shared.produced_at}"
    return load_table_upload(key_prefix, upload_label)
