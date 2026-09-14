"""Streamlit UI for the Geo Boundary Filter task."""
import pandas as pd
import streamlit as st

from config import UPLOADS_DIR
from core import pipeline
from core.ui_helpers import pick_dataframe_source
from core.utils import new_session_dir

from . import logic

_LAT_HINTS = ("lat",)
_LON_HINTS = ("lon", "lng")


def render() -> None:
    st.header("Geo Boundary Filter")
    st.caption(
        "Continue from a previous tab, or upload your own CSV/Excel file, "
        "plus a .kml boundary file. Pick which columns hold latitude and "
        "longitude — only the rows that fall inside the boundary are kept."
    )

    df, source_id = pick_dataframe_source("geo_filter")
    if df is None:
        return

    st.success(f"Loaded {len(df):,} rows x {len(df.columns)} columns.")
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(20), use_container_width=True)

    columns = list(df.columns)
    lat_default = _guess_column(columns, _LAT_HINTS)
    lon_default = _guess_column(columns, _LON_HINTS)

    col1, col2 = st.columns(2)
    with col1:
        lat_col = st.selectbox(
            "Latitude column",
            columns,
            index=columns.index(lat_default) if lat_default else 0,
            key=f"geo_lat_col_{source_id}",
        )
    with col2:
        lon_col = st.selectbox(
            "Longitude column",
            columns,
            index=columns.index(lon_default) if lon_default else 0,
            key=f"geo_lon_col_{source_id}",
        )

    kml_file = st.file_uploader("Upload boundary (.kml)", type=["kml"], key="geo_kml_upload")
    if kml_file is None:
        return

    if st.button("Filter to boundary", type="primary"):
        _run(df, lat_col, lon_col, kml_file)


def _guess_column(columns, hints):
    for col in columns:
        lowered = str(col).lower()
        if any(h in lowered for h in hints):
            return col
    return None


def _run(df: pd.DataFrame, lat_col: str, lon_col: str, kml_file) -> None:
    session_dir = new_session_dir(UPLOADS_DIR)
    kml_path = session_dir / "boundary.kml"
    kml_path.write_bytes(kml_file.getvalue())

    try:
        boundary = logic.parse_kml_boundary(kml_path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse KML boundary: {exc}")
        return

    try:
        inside_df, outside_df, stats = logic.filter_points_in_boundary(df, lat_col, lon_col, boundary)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Filtering failed: {exc}")
        return

    if stats["invalid_coords"]:
        st.warning(
            f"{stats['invalid_coords']} row(s) had non-numeric/missing "
            f"'{lat_col}' or '{lon_col}' values and were treated as outside."
        )

    st.success(
        f"{stats['inside']:,} of {stats['total_rows']:,} rows fall inside the boundary "
        f"({stats['outside']:,} outside)."
    )
    with st.expander("Preview: inside boundary", expanded=True):
        st.dataframe(inside_df.head(20), use_container_width=True)

    st.download_button(
        "Download shops inside boundary (CSV)",
        data=inside_df.to_csv(index=False),
        file_name="inside_boundary.csv",
        mime="text/csv",
    )
    with st.expander("Also download rows OUTSIDE the boundary", expanded=False):
        st.download_button(
            "Download shops outside boundary (CSV)",
            data=outside_df.to_csv(index=False),
            file_name="outside_boundary.csv",
            mime="text/csv",
            key="geo_download_outside",
        )

    pipeline.publish(inside_df, produced_by="geo_filter", task_title="Geo Boundary Filter")
    st.caption("This filtered result is now available to continue into the next tab.")
