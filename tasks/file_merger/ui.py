"""Streamlit UI for the Merge Files task."""
import shutil
from pathlib import Path

import streamlit as st

from config import OUTPUTS_DIR, UPLOADS_DIR
from core import pipeline
from core.utils import new_session_dir

from . import logic

STATE_KEY = "file_merger_session"


def render() -> None:
    st.header("Merge Files")
    st.caption(
        "Upload a .zip file with (possibly nested) folders of CSV/Excel files. "
        "Every matching file, at any depth, gets merged into one flat table — "
        "with a `source_file` column on every row so you can trace where the "
        "data came from without breaking Excel filters/pivots/sorting."
    )

    uploaded_zip = st.file_uploader("Upload a .zip file", type=["zip"], key="file_merger_zip")

    if uploaded_zip is None:
        st.session_state.pop(STATE_KEY, None)
        return

    if st.button("Extract & Scan", type="primary"):
        _extract_and_scan(uploaded_zip)

    session = st.session_state.get(STATE_KEY)
    if not session:
        return

    files = session["files"]
    if not files:
        st.warning("No .csv / .xlsx / .xls files were found inside that zip.")
        return

    st.success(f"Found {len(files)} file(s) to merge.")
    with st.expander("Files that will be merged", expanded=False):
        for f in files:
            st.text(f)

    if st.button("Merge now"):
        _merge_and_offer_download(session)


def _extract_and_scan(uploaded_zip) -> None:
    session_dir = new_session_dir(UPLOADS_DIR)
    zip_path = session_dir / "upload.zip"
    zip_path.write_bytes(uploaded_zip.getvalue())

    extract_dir = session_dir / "extracted"
    try:
        logic.extract_zip(zip_path, extract_dir)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not extract zip: {exc}")
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    discovered = logic.discover_files(extract_dir)
    st.session_state[STATE_KEY] = {
        "session_dir": str(session_dir),
        "extract_dir": str(extract_dir),
        "files": [f.rel_path for f in discovered],
    }


def _merge_and_offer_download(session: dict) -> None:
    extract_dir = Path(session["extract_dir"])
    discovered = logic.discover_files(extract_dir)
    combined_df, stats = logic.merge_files(discovered)

    if stats["errors"]:
        with st.expander(f"{len(stats['errors'])} file(s) failed to read", expanded=True):
            for err in stats["errors"]:
                st.text(err)

    if stats["files_merged"] == 0:
        st.error("Nothing could be merged.")
        return

    merged_csv = combined_df.to_csv(index=False)
    output_name = f"merged_{Path(session['session_dir']).name}.csv"
    output_path = OUTPUTS_DIR / output_name
    output_path.write_text(merged_csv, encoding="utf-8")

    st.success(f"Merged {stats['files_merged']} file(s), {stats['total_rows']} total rows.")
    with st.expander("Preview merged data", expanded=False):
        st.dataframe(combined_df.head(20), use_container_width=True)

    st.download_button(
        "Download merged CSV",
        data=merged_csv,
        file_name=output_name,
        mime="text/csv",
    )

    pipeline.publish(combined_df, produced_by="file_merger", task_title="Merge Files")
    st.caption(
        "This merged table is now available to continue straight into the "
        "next tab — no re-upload needed."
    )
