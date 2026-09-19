"""Streamlit UI for the Geo Boundary Filter task."""
import pandas as pd
import pydeck as pdk
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
        "Continue from a previous tab, or upload a CSV/Excel file, plus a "
        ".kml boundary file. Pick which columns hold latitude and "
        "longitude — every row is shown on a map and labeled **inbound** "
        "(inside the boundary) or **outbound** (outside it)."
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

    _process(df, lat_col, lon_col, kml_file)


def _guess_column(columns, hints):
    for col in columns:
        lowered = str(col).lower()
        if any(h in lowered for h in hints):
            return col
    return None


def _process(df: pd.DataFrame, lat_col: str, lon_col: str, kml_file) -> None:
    session_dir = new_session_dir(UPLOADS_DIR)
    kml_path = session_dir / "boundary.kml"
    kml_path.write_bytes(kml_file.getvalue())

    try:
        boundary = logic.parse_kml_boundary(kml_path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse KML boundary: {exc}")
        return

    try:
        processed, stats = logic.filter_points_in_boundary(df, lat_col, lon_col, boundary)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Filtering failed: {exc}")
        return

    if stats["invalid_coords"]:
        st.warning(
            f"{stats['invalid_coords']:,} row(s) had non-numeric/missing "
            f"'{lat_col}' or '{lon_col}' values — labeled outbound (there's no "
            "way to place them), and left off the map since they have no "
            "plottable location."
        )

    st.success(
        f"{stats['inbound']:,} inbound (inside boundary), "
        f"{stats['outbound']:,} outbound (outside), "
        f"out of {stats['total_rows']:,} total rows."
    )

    _render_map(processed, lat_col, lon_col, boundary)

    with st.expander("Preview processed data", expanded=False):
        st.dataframe(processed.head(20), use_container_width=True)

    inbound_df, outbound_df = logic.split_by_status(processed)

    st.subheader("Downloads")
    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        st.download_button(
            "Processed (all shops)",
            data=processed.to_csv(index=False),
            file_name="processed_all_shops.csv",
            mime="text/csv",
            key="geo_download_processed",
        )
    with dl2:
        st.download_button(
            "Inbound only",
            data=inbound_df.to_csv(index=False),
            file_name="inbound_shops.csv",
            mime="text/csv",
            key="geo_download_inbound",
        )
    with dl3:
        st.download_button(
            "Outbound only",
            data=outbound_df.to_csv(index=False),
            file_name="outbound_shops.csv",
            mime="text/csv",
            key="geo_download_outbound",
        )

    pipeline.publish(processed, produced_by="geo_filter", task_title="Geo Boundary Filter")
    st.caption(
        "The processed table (all rows, with `boundary_status`) is now available "
        "to continue straight into the next tab."
    )


def _render_map(processed: pd.DataFrame, lat_col: str, lon_col: str, boundary) -> None:
    lat = pd.to_numeric(processed[lat_col], errors="coerce")
    lon = pd.to_numeric(processed[lon_col], errors="coerce")
    plottable = lat.notna() & lon.notna()

    if not plottable.any():
        st.info("No rows have plottable coordinates — map skipped.")
        return

    map_df = pd.DataFrame(
        {
            "lat": lat[plottable],
            "lon": lon[plottable],
            "status": processed.loc[plottable, "boundary_status"],
        }
    )
    map_df["color"] = map_df["status"].map(logic.STATUS_COLORS)

    center_lat, center_lon, zoom = logic.compute_view_state(boundary)

    boundary_layer = pdk.Layer(
        "GeoJsonLayer",
        data=logic.boundary_to_geojson_feature(boundary),
        stroked=True,
        filled=True,
        get_fill_color=[0, 100, 255, 40],
        get_line_color=[0, 100, 255, 200],
        line_width_min_pixels=2,
    )
    points_layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_df,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=40,
        radius_min_pixels=3,
        radius_max_pixels=15,
        pickable=True,
    )

    st.pydeck_chart(
        pdk.Deck(
            layers=[boundary_layer, points_layer],
            initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom),
            tooltip={"text": "{status}"},
        )
    )
    st.caption("🟢 green = inbound (inside boundary)  •  🔴 red = outbound (outside boundary)")
