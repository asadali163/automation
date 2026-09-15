"""Streamlit UI for the Merge CSVs task — upload two or more CSV/Excel
files directly (no zip, no nested folders), review + optionally drop
columns per file (handy for making two files' columns line up before
merging), then merge them into one table.

Always starts from a fresh upload; unlike the other tasks it does not
offer to continue from a previous tab's output.
"""
import pandas as pd
import streamlit as st

from config import OUTPUTS_DIR, UPLOADS_DIR
from core import pipeline
from core.io import read_table
from core.utils import new_session_dir, short_id

from . import logic


def render() -> None:
    st.header("Merge CSVs")
    st.caption(
        "Upload two or more .csv/.xlsx/.xls files directly — no zip, no "
        "folders. Review the columns below and remove any you don't want "
        "from a given file (handy when one file has an extra column and "
        "you want both files' columns to line up), then merge into one table."
    )

    uploaded_files = st.file_uploader(
        "Upload files",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="csv_merger_upload",
    )

    if not uploaded_files:
        return

    if len(uploaded_files) < 2:
        st.info("Upload at least 2 files to merge.")
        return

    loaded = _load_uploads(uploaded_files)
    if loaded is None:
        return

    st.subheader("All columns across files")
    st.dataframe(_columns_overview(loaded), use_container_width=True)

    st.subheader("Remove columns (optional)")
    columns_to_drop = {}
    for entry in loaded:
        with st.expander(
            f"{entry['label']} — {len(entry['df']):,} rows x {len(entry['df'].columns)} columns",
            expanded=True,
        ):
            selected = st.multiselect(
                "Columns to remove from this file",
                options=list(entry["df"].columns),
                key=f"csv_merger_drop_{entry['id']}",
            )
            columns_to_drop[entry["id"]] = selected
            if selected:
                remaining = [c for c in entry["df"].columns if c not in selected]
                st.caption(f"Remaining columns: {', '.join(remaining) or '(none)'}")

    if st.button("Merge now", type="primary"):
        _merge_and_offer_download(loaded, columns_to_drop)


def _load_uploads(uploaded_files):
    """Read every uploaded file into a DataFrame once, cached in
    session_state by (name, size) so adjusting a multiselect doesn't
    re-parse files on every rerun. Returns a list of
    {"id", "label", "df"} dicts, or None if a file failed to read.
    """
    session_dir = None
    loaded = []
    for i, uploaded in enumerate(uploaded_files):
        file_id = f"{uploaded.name}_{uploaded.size}_{i}"
        cache_key = f"csv_merger_df_{file_id}"
        if cache_key not in st.session_state:
            if session_dir is None:
                session_dir = new_session_dir(UPLOADS_DIR)
            file_path = session_dir / f"{i:02d}_{uploaded.name}"
            file_path.write_bytes(uploaded.getvalue())
            try:
                st.session_state[cache_key] = read_table(file_path)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read {uploaded.name}: {exc}")
                return None
        loaded.append({"id": file_id, "label": uploaded.name, "df": st.session_state[cache_key]})
    return loaded


def _columns_overview(loaded) -> pd.DataFrame:
    """A file-x-column presence matrix, so mismatches are visible at a glance."""
    all_columns = []
    seen = set()
    for entry in loaded:
        for c in entry["df"].columns:
            if c not in seen:
                seen.add(c)
                all_columns.append(c)

    return pd.DataFrame(
        {entry["label"]: ["✓" if c in entry["df"].columns else "" for c in all_columns] for entry in loaded},
        index=all_columns,
    )


def _merge_and_offer_download(loaded, columns_to_drop) -> None:
    labeled_dfs = [
        (entry["label"], logic.drop_columns(entry["df"], columns_to_drop.get(entry["id"], [])))
        for entry in loaded
    ]
    combined_df, stats = logic.merge_csvs(labeled_dfs)

    merged_csv = combined_df.to_csv(index=False)
    output_name = f"merged_csvs_{short_id()}.csv"
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

    pipeline.publish(combined_df, produced_by="csv_merger", task_title="Merge CSVs")
    st.caption(
        "This merged table is now available to continue straight into the "
        "next tab (e.g. Deduplication) — no re-upload needed."
    )
