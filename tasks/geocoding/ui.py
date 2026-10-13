"""Streamlit UI for the Geocoding task."""
from typing import List, Optional

import pandas as pd
import streamlit as st

from core import pipeline
from core.ui_helpers import pick_dataframe_source
from core.utils import short_id

from . import logic

_LAT_HINTS = ("lat",)
_LON_HINTS = ("lon", "lng")
_ADDRESS_HINTS = ("address",)

_MODE_FORWARD = "Address → Coordinates"
_MODE_REVERSE = "Coordinates → Address"


def render() -> None:
    st.header("Geocoding")
    st.caption(
        "Continue from a previous tab, or upload a CSV/Excel file. Two "
        "providers are tried per lookup, in order: **Nominatim** "
        "(OpenStreetMap, free, no key) first, then **Geoapify** for "
        "anything Nominatim couldn't resolve."
    )

    df, source_id = pick_dataframe_source("geocode")
    if df is None:
        return

    st.success(f"Loaded {len(df):,} rows x {len(df.columns)} columns.")
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(20), use_container_width=True)

    mode = st.radio(
        "Direction",
        [_MODE_FORWARD, _MODE_REVERSE],
        key=f"geocode_mode_{source_id}",
        horizontal=True,
    )

    api_key = _get_api_key()
    if not api_key:
        st.warning(
            "No Geoapify API key configured — running Nominatim only. Lookups "
            "it can't resolve will come back as `not_found`. Add a key to "
            "`.streamlit/secrets.toml` to enable the fallback."
        )

    if mode == _MODE_FORWARD:
        _render_forward(df, source_id, api_key)
    else:
        _render_reverse(df, source_id, api_key)


def _get_api_key() -> Optional[str]:
    """Prefer a key configured in .streamlit/secrets.toml (gitignored, never
    committed); fall back to a per-session password field otherwise.
    """
    try:
        configured = st.secrets.get("GEOAPIFY_API_KEY")
    except Exception:  # noqa: BLE001 - no secrets.toml at all
        configured = None
    if configured:
        return configured

    return st.text_input(
        "Geoapify API key (optional — used only as fallback)",
        type="password",
        key="geocode_api_key_input",
        help=(
            f"Free tier: {logic.DAILY_REQUEST_LIMIT:,} requests/day. Only the "
            "lookups Nominatim fails on are sent here, so this goes a long way. "
            "Set GEOAPIFY_API_KEY in .streamlit/secrets.toml to skip this field."
        ),
    )


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} hours"


def _guess_column(columns, hints):
    for col in columns:
        if any(h in str(col).lower() for h in hints):
            return col
    return None


# --- Address -> Coordinates --------------------------------------------------------


def _render_forward(df: pd.DataFrame, source_id: str, api_key: Optional[str]) -> None:
    columns = list(df.columns)
    col1, col2 = st.columns(2)
    with col1:
        primary_col = st.selectbox("Address column", columns, key=f"geocode_col1_{source_id}")
    with col2:
        secondary_options = ["(none)"] + [c for c in columns if c != primary_col]
        secondary_col = st.selectbox(
            "Additional column (optional, e.g. city/postal code)",
            secondary_options,
            key=f"geocode_col2_{source_id}",
        )
    address_cols: List[str] = [primary_col] + ([] if secondary_col == "(none)" else [secondary_col])

    country_code = st.text_input(
        "Country code (optional)",
        max_chars=2,
        key=f"geocode_country_{source_id}",
        help=(
            "Two-letter code, e.g. hu / nl / lu. Restricts Nominatim results to "
            "that country, which noticeably improves accuracy when the file is "
            "single-country. Leave blank to search worldwide."
        ),
    ).strip().lower()

    unique_queries = logic.count_unique_queries(df, address_cols)
    est_seconds = unique_queries * logic.NOMINATIM_DELAY
    st.caption(
        f"{unique_queries:,} unique address(es) out of {len(df):,} rows (repeats cached) — "
        f"roughly {_format_duration(est_seconds)} at Nominatim's ~1 lookup/second "
        "(longer for addresses that need several attempts)."
    )

    if st.button("Start geocoding", type="primary", key="geocode_run_forward"):
        _run_forward(df, address_cols, country_code, api_key)


def _run_forward(df: pd.DataFrame, address_cols: List[str], country_code: str, api_key: Optional[str]) -> None:
    providers = [logic.build_nominatim_fn(country_code=country_code)]
    if api_key:
        providers.append(logic.build_geoapify_fn(api_key))
    geocode_fn = logic.chain_providers(providers)

    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def on_progress(done: int, total: int) -> None:
        progress_bar.progress(done / total if total else 1.0)
        status_text.text(f"Geocoded {done:,} / {total:,} rows...")

    result_df = logic.geocode_dataframe(df, address_cols, geocode_fn, progress_callback=on_progress)
    stats = logic.summarise(result_df)

    progress_bar.empty()
    status_text.empty()

    by_provider = stats["by_provider"]
    breakdown = ", ".join(f"{count:,} via {name}" for name, count in by_provider.items()) or "none"
    st.success(
        f"Done: {stats['geocoded']:,} of {stats['total_rows']:,} rows resolved ({breakdown}); "
        f"{stats['not_found']:,} not found, {stats['empty_address']:,} had no address."
    )

    with st.expander("Preview result", expanded=True):
        st.dataframe(result_df.head(20), use_container_width=True)

    st.download_button(
        "Download geocoded CSV",
        data=result_df.to_csv(index=False),
        file_name=f"geocoded_{short_id()}.csv",
        mime="text/csv",
        key="geocode_download_forward",
    )

    pipeline.publish(result_df, produced_by="geocoding", task_title="Geocoding")
    st.caption(
        "Added `latitude`, `longitude`, `geocode_status`, `geocode_source` (which "
        "service resolved it) and `geocode_query` (which address variant worked). "
        "Also available to continue into another tab."
    )


# --- Coordinates -> Address --------------------------------------------------------


def _render_reverse(df: pd.DataFrame, source_id: str, api_key: Optional[str]) -> None:
    columns = list(df.columns)
    lat_default = _guess_column(columns, _LAT_HINTS)
    lon_default = _guess_column(columns, _LON_HINTS)

    col1, col2 = st.columns(2)
    with col1:
        lat_col = st.selectbox(
            "Latitude column",
            columns,
            index=columns.index(lat_default) if lat_default else 0,
            key=f"geocode_rev_lat_{source_id}",
        )
    with col2:
        lon_col = st.selectbox(
            "Longitude column",
            columns,
            index=columns.index(lon_default) if lon_default else 0,
            key=f"geocode_rev_lon_{source_id}",
        )

    address_options = ["(none — add a new column)"] + [c for c in columns if c not in (lat_col, lon_col)]
    address_default = _guess_column(columns, _ADDRESS_HINTS)
    address_choice = st.selectbox(
        "Existing address column (optional)",
        address_options,
        index=address_options.index(address_default) if address_default in address_options else 0,
        key=f"geocode_rev_address_col_{source_id}",
        help=(
            "If your file already has an address column, pick it here: only the "
            "rows where it's blank get looked up, and the result fills those "
            "blanks in place — every row that already has a value is left "
            "completely untouched. Leave as '(none)' to look up every row into "
            "a brand-new `reverse_address` column instead."
        ),
    )
    address_col = None if address_choice.startswith("(none") else address_choice

    unique_coords = logic.count_unique_coords(df, lat_col, lon_col, address_col=address_col)
    est_seconds = unique_coords * logic.NOMINATIM_DELAY
    if address_col:
        st.caption(
            f"{unique_coords:,} row(s) are missing '{address_col}' out of {len(df):,} total "
            f"(repeats cached) — only those get looked up; roughly {_format_duration(est_seconds)} "
            "at Nominatim's ~1 lookup/second. Every other row stays exactly as it is."
        )
    else:
        st.caption(
            f"{unique_coords:,} unique coordinate pair(s) out of {len(df):,} rows (repeats cached) — "
            f"roughly {_format_duration(est_seconds)} at Nominatim's ~1 lookup/second."
        )

    if st.button("Start reverse geocoding", type="primary", key="geocode_run_reverse"):
        _run_reverse(df, lat_col, lon_col, address_col, api_key)


def _run_reverse(
    df: pd.DataFrame, lat_col: str, lon_col: str, address_col: Optional[str], api_key: Optional[str]
) -> None:
    providers = [logic.build_nominatim_reverse_fn()]
    if api_key:
        providers.append(logic.build_geoapify_reverse_fn(api_key))
    reverse_fn = logic.chain_providers(providers)

    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def on_progress(done: int, total: int) -> None:
        progress_bar.progress(done / total if total else 1.0)
        status_text.text(f"Reverse geocoded {done:,} / {total:,} rows...")

    result_df = logic.reverse_geocode_dataframe(
        df, lat_col, lon_col, reverse_fn, address_col=address_col, progress_callback=on_progress
    )
    stats = logic.summarise_reverse(result_df)

    progress_bar.empty()
    status_text.empty()

    by_provider = stats["by_provider"]
    breakdown = ", ".join(f"{count:,} via {name}" for name, count in by_provider.items()) or "none"
    st.success(
        f"Done: {stats['already_had_address']:,} already had an address (untouched), "
        f"{stats['geocoded']:,} newly resolved ({breakdown}); "
        f"{stats['not_found']:,} not found, {stats['invalid_coords']:,} had invalid coordinates."
    )

    with st.expander("Preview result", expanded=True):
        st.dataframe(result_df.head(20), use_container_width=True)

    st.download_button(
        "Download reverse-geocoded CSV",
        data=result_df.to_csv(index=False),
        file_name=f"reverse_geocoded_{short_id()}.csv",
        mime="text/csv",
        key="geocode_download_reverse",
    )

    pipeline.publish(result_df, produced_by="geocoding", task_title="Geocoding")
    if address_col:
        st.caption(
            f"Only the blank rows in '{address_col}' were looked up and filled in — "
            "every other row's address is exactly as it was. Also available to "
            "continue into another tab."
        )
    else:
        st.caption(
            "Added `reverse_address`, `reverse_geocode_status` and `reverse_geocode_source` "
            "(which service resolved it) — kept separate from any existing address column "
            "in your data. Also available to continue into another tab."
        )
