"""Lets one task's output become the next task's input, so you don't have
to re-upload merged/deduped data at every step.

Backed by `st.session_state` only — per-browser-session, nothing written to
disk, and it resets when the tab is closed or the app restarts. A task
calls `publish()` after producing a result; the next task calls `get()`
(usually via `core.ui_helpers.pick_dataframe_source`) to offer it as a
"continue from here" option alongside a fresh upload.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

_STATE_KEY = "pipeline_shared_dataset"


@dataclass(frozen=True)
class SharedDataset:
    df: pd.DataFrame
    label: str          # e.g. "Merge Files output (14,332 rows)"
    produced_by: str      # id of the task that produced it
    produced_at: str       # human-readable timestamp, for display only


def publish(df: pd.DataFrame, produced_by: str, task_title: str) -> None:
    """Call this after a task finishes, so downstream tasks can reuse the result."""
    st.session_state[_STATE_KEY] = SharedDataset(
        df=df,
        label=f"{task_title} output ({len(df):,} rows)",
        produced_by=produced_by,
        produced_at=datetime.now().strftime("%H:%M:%S"),
    )


def get() -> Optional[SharedDataset]:
    return st.session_state.get(_STATE_KEY)


def clear() -> None:
    st.session_state.pop(_STATE_KEY, None)
