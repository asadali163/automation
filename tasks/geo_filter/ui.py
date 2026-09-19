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
_DETAIL_HINTS = ("name", "shop", "address", "license")

_SHOPS_LAYER_ID = "shops"


def render() -> None:
    st.header("Geo Boundary Filter")
    st.caption(
        "Continue from a previous tab, or upload a CSV/Excel file, plus a "
        ".kml boundary file. Pick which columns hold latitude and "
        "longitude — every row is shown on a map and labeled **inbound** "
        "(inside the boundary) or **outbound** (outside it). Click a shop "
        "on the map to see its details."
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

    detail_columns = st.multiselect(
        "Columns to show when you click a shop on the map",
        options=[c for c in columns if c not in (lat_col, lon_col)],
        default=_guess_detail_defaults(columns, exclude=(lat_col, lon_col)),
        key=f"geo_detail_cols_{source_id}",
    )

    kml_file = st.file_uploader("Upload boundary (.kml)", type=["kml"], key="geo_kml_upload")
    if kml_file is None:
        return

    _process(df, lat_col, lon_col, detail_columns, kml_file, source_id)


def _guess_column(columns, hints):
    for col in columns:
        lowered = str(col).lower()
        if any(h in lowered for h in hints):
            return col
    return None


def _guess_detail_defaults(columns, exclude, limit=3):
    excluded = set(exclude)
    hinted = [c for c in columns if c not in excluded and any(h in str(c).lower() for h in _DETAIL_HINTS)]
    if hinted:
        return hinted[:limit]
    remaining = [c for c in columns if c not in excluded]
    return remaining[: min(2, len(remaining))]


def _process(
    df: pd.DataFrame, lat_col: str, lon_col: str, detail_columns: list, kml_file, source_id: str
) -> None:
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

    _render_map(processed, lat_col, lon_col, detail_columns, boundary, source_id)

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


def _render_map(
    processed: pd.DataFrame, lat_col: str, lon_col: str, detail_columns: list, boundary, source_id: str
) -> None:
    lat = pd.to_numeric(processed[lat_col], errors="coerce")
    lon = pd.to_numeric(processed[lon_col], errors="coerce")
    plottable = lat.notna() & lon.notna()

    if not plottable.any():
        st.info("No rows have plottable coordinates — map skipped.")
        return

    fields = logic.build_detail_fields(detail_columns)

    map_df = pd.DataFrame(
        {
            "lat": lat[plottable],
            "lon": lon[plottable],
            "status": processed.loc[plottable, "boundary_status"],
        }
    )
    for key, col in fields:
        map_df[key] = processed.loc[plottable, col].astype(str)
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
        id=_SHOPS_LAYER_ID,
        data=map_df,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=40,
        radius_min_pixels=4,
        radius_max_pixels=16,
        pickable=True,
        auto_highlight=True,
    )

    tooltip_html = "<b>Status:</b> {status}" + "".join(f"<br/><b>{label}:</b> {{{key}}}" for key, label in fields)

    event = st.pydeck_chart(
        pdk.Deck(
            layers=[boundary_layer, points_layer],
            initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom),
            tooltip={"html": tooltip_html, "style": {"backgroundColor": "white", "color": "black"}},
        ),
        on_select="rerun",
        selection_mode="single-object",
        key=f"geo_map_{source_id}",
    )
    st.caption("🟢 green = inbound  •  🔴 red = outbound  •  hover for a quick preview, click for full details")

    _render_selected_details(event, fields, lat_col, lon_col)


def _render_selected_details(event, fields, lat_col: str, lon_col: str) -> None:
    selected = []
    if event and event.selection:
        selected = event.selection.objects.get(_SHOPS_LAYER_ID, [])

    if not selected:
        st.caption("No shop selected — click one on the map above.")
        return

    shop = selected[0]
    status = shop.get("status")
    rows = [("Status", "Inbound ✅" if status == logic.STATUS_INBOUND else "Outbound ❌")]
    for key, label in fields:
        rows.append((label, shop.get(key, "")))
    rows.append((lat_col, shop.get("lat", "")))
    rows.append((lon_col, shop.get("lon", "")))

    st.markdown("**Selected shop**")
    st.table(pd.DataFrame(rows, columns=["Field", "Value"]).set_index("Field"))
