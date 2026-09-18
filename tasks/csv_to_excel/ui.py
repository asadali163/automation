"""Streamlit UI for the CSV to Excel task — upload a .csv file, download it
back as an .xlsx file. No other changes made to the data.
"""
from pathlib import Path

import streamlit as st

from config import UPLOADS_DIR
from core.io import read_table
from core.utils import new_session_dir

from . import logic


def render() -> None:
    st.header("CSV to Excel")
    st.caption("Upload a .csv file and download it as an .xlsx file.")

    uploaded = st.file_uploader("Upload a .csv file", type=["csv"], key="csv_to_excel_upload")
    if uploaded is None:
        return

    session_dir = new_session_dir(UPLOADS_DIR)
    file_path = session_dir / "input.csv"
    file_path.write_bytes(uploaded.getvalue())

    try:
        df = read_table(file_path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read file: {exc}")
        return

    st.success(f"Loaded {len(df):,} rows x {len(df.columns)} columns.")
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(20), use_container_width=True)

    excel_bytes = logic.dataframe_to_excel_bytes(df)
    output_name = f"{Path(uploaded.name).stem}.xlsx"

    st.download_button(
        "Download Excel file",
        data=excel_bytes,
        file_name=output_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
