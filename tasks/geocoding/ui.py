"""Streamlit UI for the Geocoding task."""
from typing import List, Optional

import pandas as pd
import streamlit as st

from core import pipeline
from core.ui_helpers import pick_dataframe_source
from core.utils import short_id

from . import logic


def render() -> None:
    st.header("Geocoding")
    st.caption(
        "Continue from a previous tab, or upload a CSV/Excel file. Pick the "
        "column(s) holding the address, and each row is resolved to "
        "coordinates — **Nominatim (OpenStreetMap) first**, trying "
        "progressively simpler variants of the address, then **Geoapify** "
        "for anything Nominatim couldn't find."
    )

    df, source_id = pick_dataframe_source("geocode")
    if df is None:
        return

    st.success(f"Loaded {len(df):,} rows x {len(df.columns)} columns.")
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(20), use_container_width=True)

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

    api_key = _get_api_key()

    unique_queries = logic.count_unique_queries(df, address_cols)
    est_seconds = unique_queries * logic.NOMINATIM_DELAY
    st.caption(
        f"{unique_queries:,} unique address(es) out of {len(df):,} rows (repeats cached) — "
        f"roughly {_format_duration(est_seconds)} at Nominatim's ~1 lookup/second "
        "(longer for addresses that need several attempts)."
    )

    if not api_key:
        st.warning(
            "No Geoapify API key configured — running Nominatim only. Addresses it "
            f"can't resolve will come back as `not_found`. Add a key to "
            "`.streamlit/secrets.toml` to enable the fallback."
        )

    if st.button("Start geocoding", type="primary"):
        _run(df, address_cols, country_code, api_key)


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
            f"Free tier: {logic.DAILY_REQUEST_LIMIT:,} requests/day. Only the addresses "
            "Nominatim fails on are sent here, so this goes a long way. Set "
            "GEOAPIFY_API_KEY in .streamlit/secrets.toml to skip this field."
        ),
    )


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} hours"


def _run(df: pd.DataFrame, address_cols: List[str], country_code: str, api_key: Optional[str]) -> None:
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
    )

    pipeline.publish(result_df, produced_by="geocoding", task_title="Geocoding")
    st.caption(
        "Added `latitude`, `longitude`, `geocode_status`, `geocode_source` (which "
        "service resolved it) and `geocode_query` (which address variant worked). "
        "Also available to continue into another tab."
    )
