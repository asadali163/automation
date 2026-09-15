"""Dashboard entry point.

Do NOT hardcode tasks here — drop a new package under `tasks/` (see
`tasks/file_merger` as a template) and it shows up automatically as a tab.
"""

import streamlit as st

from config import OUTPUTS_DIR, UPLOADS_DIR
from core.task_registry import discover_tasks
from core.utils import cleanup_old_dirs

st.set_page_config(page_title="Automation Dashboard", page_icon="⚙️", layout="wide")

cleanup_old_dirs(UPLOADS_DIR)
cleanup_old_dirs(OUTPUTS_DIR)

st.title("Automation Dashboard")

tasks = discover_tasks()

if not tasks:
    st.info("No tasks registered yet. Add a module under `tasks/`.")
else:
    tabs = st.tabs([f"{t.icon} {t.title}".strip() if t.icon else t.title for t in tasks])
    for tab, task in zip(tabs, tasks):
        with tab:
            task.render()
