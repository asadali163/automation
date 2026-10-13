"""Pure logic for the Geocoding task — no Streamlit here.

Two directions, each trying the same two providers in order:

- **Forward** (address -> coordinates): `build_nominatim_fn` / `build_geoapify_fn` / `geocode_dataframe`
- **Reverse** (coordinates -> address): `build_nominatim_reverse_fn` / `build_geoapify_reverse_fn` / `reverse_geocode_dataframe`

1. **Nominatim** (OpenStreetMap) — free, no key. Forward lookups walk a
   ladder of progressively simpler address variants (raw -> district marker
   stripped -> house-number range/suffix simplified -> street only), which is
   what lifts the hit rate dramatically on messy official-register addresses.
   Rate-limited to ~1 req/sec per Nominatim's usage policy.
2. **Geoapify** — used only for what Nominatim couldn't resolve, so it burns
   very few of the free tier's 3,000 requests/day.

Identical lookups (same address, or same coordinate pair) are only made
once per run (cached).
"""
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import requests

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {"User-Agent": "Automation-Project/1.0 (personal data automation project)"}
NOMINATIM_DELAY = 1.1  # Nominatim usage policy: max 1 req/sec

GEOAPIFY_SEARCH_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_REVERSE_URL = "https://api.geoapify.com/v1/geocode/reverse"
DAILY_REQUEST_LIMIT = 3000  # Geoapify free-tier cap

# kept for backwards compatibility with earlier code/tests that reference the
# forward-search URL under its original name
NOMINATIM_URL = NOMINATIM_SEARCH_URL
GEOAPIFY_URL = GEOAPIFY_SEARCH_URL

PROVIDER_NOMINATIM = "nominatim"
PROVIDER_GEOAPIFY = "geoapify"


@dataclass(frozen=True)
class GeocodeHit:
    latitude: float
    longitude: float
    provider: str      # which service resolved it
    query_used: str     # the address variant that actually worked


@dataclass(frozen=True)
class ReverseHit:
    address: str
    provider: str   # which service resolved it


GeocodeFn = Callable[[str], Optional[GeocodeHit]]
ReverseGeocodeFn = Callable[[float, float], Optional[ReverseHit]]


# --- address normalisation ladder -------------------------------------------------
# Each step makes the address a little easier for a free-form geocoder to parse.
# They're tried in order and the first variant that resolves wins.


def strip_district(addr: str) -> str:
    """Drop a redundant district marker, e.g.
    "1071 Budapest 07. ker. Rottenbiller utca 49." -> "1071 Budapest Rottenbiller utca 49."
    Nominatim's free-form parser often chokes on these.
    """
    addr = re.sub(r"\b\d{1,2}\.\s*ker\.\s*", "", addr)
    return re.sub(r"\s+", " ", addr).strip()


def simplify_house_number(addr: str) -> str:
    """Take the first number of a range and drop floor/unit suffixes, e.g.
    "Zsókavár utca 43-47 fszt" -> "Zsókavár utca 43."
    """
    addr = re.sub(r"(\d+)\s*-\s*\d+", r"\1", addr)
    addr = re.sub(
        r"(\d+(?:/[A-Za-z])?)\.?\s+[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű.]+\s*$",
        r"\1.",
        addr,
    )
    return re.sub(r"\s+", " ", addr).strip()


def street_only(addr: str) -> str:
    """Last resort: drop the house number entirely, keeping postal code/city/street."""
    return re.sub(r"\s+\d+.*$", "", addr).strip()


def build_candidates(address: str) -> List[str]:
    """The ordered, de-duplicated list of address variants to try."""
    seen = set()
    candidates = []
    for candidate in [
        address,
        strip_district(address),
        simplify_house_number(strip_district(address)),
        street_only(strip_district(address)),
    ]:
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


# --- providers --------------------------------------------------------------------


def build_nominatim_fn(
    country_code: str = "",
    delay_seconds: float = NOMINATIM_DELAY,
    timeout: float = 15.0,
) -> GeocodeFn:
    """Nominatim lookup that walks the candidate ladder until one resolves.

    `country_code` (e.g. "hu", "nl") restricts results to one country, which
    noticeably improves accuracy when you know the data is single-country;
    leave blank to search worldwide.
    """

    def geocode(address: str) -> Optional[GeocodeHit]:
        for query in build_candidates(address):
            params = {"q": query, "format": "json", "limit": 1}
            if country_code:
                params["countrycodes"] = country_code
            response = requests.get(
                NOMINATIM_SEARCH_URL, params=params, headers=NOMINATIM_HEADERS, timeout=timeout
            )
            response.raise_for_status()
            results = response.json()
            time.sleep(delay_seconds)  # usage policy: max 1 req/sec
            if results:
                return GeocodeHit(
                    latitude=float(results[0]["lat"]),
                    longitude=float(results[0]["lon"]),
                    provider=PROVIDER_NOMINATIM,
                    query_used=query,
                )
        return None

    return geocode


def build_geoapify_fn(api_key: str, timeout: float = 10.0) -> GeocodeFn:
    """Geoapify lookup — the fallback for addresses Nominatim can't resolve.

    Deliberately queries the raw address only (no candidate ladder): it's a
    more forgiving parser, and this keeps it to one request per fallback
    address against the daily cap.
    """

    def geocode(address: str) -> Optional[GeocodeHit]:
        response = requests.get(
            GEOAPIFY_SEARCH_URL,
            params={"text": address, "apiKey": api_key, "format": "json", "limit": 1},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            return None
        lat, lon = results[0].get("lat"), results[0].get("lon")
        if lat is None or lon is None:
            return None
        return GeocodeHit(
            latitude=float(lat),
            longitude=float(lon),
            provider=PROVIDER_GEOAPIFY,
            query_used=address,
        )

    return geocode


# --- reverse providers (coordinates -> address) ------------------------------------


def build_nominatim_reverse_fn(
    delay_seconds: float = NOMINATIM_DELAY,
    timeout: float = 15.0,
) -> ReverseGeocodeFn:
    """Nominatim reverse lookup: one coordinate pair -> one address."""

    def reverse(lat: float, lon: float) -> Optional[ReverseHit]:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={"lat": lat, "lon": lon, "format": "json"},
            headers=NOMINATIM_HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        time.sleep(delay_seconds)  # usage policy: max 1 req/sec
        address = data.get("display_name") if isinstance(data, dict) else None
        if not address:
            return None
        return ReverseHit(address=address, provider=PROVIDER_NOMINATIM)

    return reverse


def build_geoapify_reverse_fn(api_key: str, timeout: float = 10.0) -> ReverseGeocodeFn:
    """Geoapify reverse lookup — the fallback for coordinates Nominatim can't resolve."""

    def reverse(lat: float, lon: float) -> Optional[ReverseHit]:
        response = requests.get(
            GEOAPIFY_REVERSE_URL,
            params={"lat": lat, "lon": lon, "apiKey": api_key, "format": "json"},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            return None
        address = results[0].get("formatted")
        if not address:
            return None
        return ReverseHit(address=address, provider=PROVIDER_GEOAPIFY)

    return reverse


def chain_providers(providers: List[Callable]) -> Callable:
    """Try each provider in order (forward or reverse, any argument shape);
    the first hit wins.

    A provider that raises (network error, rate limit, bad key) is skipped so
    the next one still gets its turn — an outage in the primary degrades to
    the fallback instead of failing the row.
    """

    def run(*args, **kwargs):
        for provider in providers:
            try:
                hit = provider(*args, **kwargs)
            except Exception:  # noqa: BLE001 - provider failed, fall through to the next
                continue
            if hit is not None:
                return hit
        return None

    return run


# --- dataframe-level driver -------------------------------------------------------


def build_queries(df: pd.DataFrame, address_cols: List[str]) -> pd.Series:
    """One address string per row, joining the chosen column(s) and skipping
    blank values (e.g. a missing 'city' doesn't leave a stray ", " separator).
    """
    if not address_cols:
        return pd.Series([""] * len(df), index=df.index)

    parts = pd.concat([df[c].astype(str).str.strip() for c in address_cols], axis=1)
    return parts.apply(lambda row: ", ".join(v for v in row if v), axis=1)


def count_unique_queries(df: pd.DataFrame, address_cols: List[str]) -> int:
    """How many distinct, non-blank addresses would actually be looked up."""
    queries = build_queries(df, address_cols)
    return int(queries[queries != ""].nunique())


def geocode_dataframe(
    df: pd.DataFrame,
    address_cols: List[str],
    geocode_fn: GeocodeFn,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Add `latitude`, `longitude`, `geocode_status`, `geocode_source` and
    `geocode_query` columns to a copy of `df`.

    `geocode_source` records which provider resolved the row, and
    `geocode_query` which address variant worked — so you can see exactly how
    each coordinate was obtained. Repeated addresses are looked up once.
    """
    result = df.copy()
    queries = build_queries(df, address_cols)

    latitudes: List[Optional[float]] = []
    longitudes: List[Optional[float]] = []
    statuses: List[str] = []
    sources: List[str] = []
    used_queries: List[str] = []
    cache: Dict[str, Optional[GeocodeHit]] = {}

    total = len(result)
    for i, address in enumerate(queries, start=1):
        if not address:
            hit, status = None, "empty_address"
        else:
            if address not in cache:
                try:
                    cache[address] = geocode_fn(address)
                except Exception:  # noqa: BLE001 - every provider failed
                    cache[address] = None
            hit = cache[address]
            status = "ok" if hit else "not_found"

        latitudes.append(hit.latitude if hit else None)
        longitudes.append(hit.longitude if hit else None)
        statuses.append(status)
        sources.append(hit.provider if hit else "")
        used_queries.append(hit.query_used if hit else "")

        if progress_callback:
            progress_callback(i, total)

    result["latitude"] = latitudes
    result["longitude"] = longitudes
    result["geocode_status"] = statuses
    result["geocode_source"] = sources
    result["geocode_query"] = used_queries

    return result


def summarise(result: pd.DataFrame) -> Dict:
    """Counts for a forward-geocode run: totals, per-status and per-provider breakdown."""
    statuses = list(result["geocode_status"])
    by_provider = Counter(s for s in result["geocode_source"] if s)
    return {
        "total_rows": len(result),
        "geocoded": statuses.count("ok"),
        "not_found": statuses.count("not_found"),
        "empty_address": statuses.count("empty_address"),
        "by_provider": dict(by_provider),
    }


# --- reverse dataframe-level driver (coordinates -> address) ----------------------


def _numeric_coords(df: pd.DataFrame, lat_col: str, lon_col: str) -> Tuple[pd.Series, pd.Series]:
    return pd.to_numeric(df[lat_col], errors="coerce"), pd.to_numeric(df[lon_col], errors="coerce")


def missing_value_mask(series: pd.Series) -> pd.Series:
    """True wherever `series` has no real value yet — NaN, or blank/
    whitespace-only once stringified (covers both an actually-empty cell
    and a text column that literally contains "" or "nan").
    """
    stripped = series.astype(str).str.strip()
    return series.isna() | (stripped == "") | (stripped.str.lower() == "nan")


def count_unique_coords(df: pd.DataFrame, lat_col: str, lon_col: str, address_col: Optional[str] = None) -> int:
    """How many distinct coordinate pairs would actually be looked up
    (coordinates rounded to 6 decimal places — ~0.1m — before dedup, same
    as `reverse_geocode_dataframe` uses for its cache).

    If `address_col` names an existing column, rows that already have a
    value there are excluded — they won't be looked up at all.
    """
    lat, lon = _numeric_coords(df, lat_col, lon_col)
    valid = lat.notna() & lon.notna()
    if address_col and address_col in df.columns:
        valid = valid & missing_value_mask(df[address_col])
    pairs = {(round(la, 6), round(lo, 6)) for la, lo in zip(lat[valid], lon[valid])}
    return len(pairs)


def reverse_geocode_dataframe(
    df: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    reverse_fn: ReverseGeocodeFn,
    address_col: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """Fill in a reverse-geocoded address on a copy of `df`.

    If `address_col` names an existing column: only the rows where it's
    blank are looked up — every row that already has a value is left
    completely untouched (no API call, no change), and the result fills
    in that *same* column rather than adding a new one. If `address_col`
    is omitted (or doesn't exist yet), every row with valid coordinates is
    looked up into a new `reverse_address` column.

    Either way, `reverse_geocode_status` records what happened to each row
    ("existing" / "ok" / "not_found" / "invalid_coords") and
    `reverse_geocode_source` which service resolved it. Repeated coordinate
    pairs (rounded to 6 decimal places) are only looked up once.
    """
    result = df.copy()
    lat, lon = _numeric_coords(df, lat_col, lon_col)

    fill_in_place = bool(address_col) and address_col in df.columns
    output_col = address_col if fill_in_place else "reverse_address"
    needs_lookup = missing_value_mask(df[address_col]) if fill_in_place else pd.Series(True, index=df.index)
    existing = df[address_col] if fill_in_place else None

    addresses: List[str] = []
    statuses: List[str] = []
    sources: List[str] = []
    cache: Dict[Tuple[float, float], Optional[ReverseHit]] = {}

    total = len(result)
    for i, (la, lo, need) in enumerate(zip(lat, lon, needs_lookup), start=1):
        hit = None
        if not need:
            address, status = str(existing.iloc[i - 1]), "existing"
        elif pd.isna(la) or pd.isna(lo):
            address, status = "", "invalid_coords"
        else:
            key = (round(float(la), 6), round(float(lo), 6))
            if key not in cache:
                try:
                    cache[key] = reverse_fn(*key)
                except Exception:  # noqa: BLE001 - every provider failed
                    cache[key] = None
            hit = cache[key]
            address = hit.address if hit else ""
            status = "ok" if hit else "not_found"

        addresses.append(address)
        statuses.append(status)
        sources.append(hit.provider if hit else "")

        if progress_callback:
            progress_callback(i, total)

    result[output_col] = addresses
    result["reverse_geocode_status"] = statuses
    result["reverse_geocode_source"] = sources

    return result


def summarise_reverse(result: pd.DataFrame) -> Dict:
    """Counts for a reverse-geocode run: totals, per-status and per-provider breakdown."""
    statuses = list(result["reverse_geocode_status"])
    by_provider = Counter(s for s in result["reverse_geocode_source"] if s)
    return {
        "total_rows": len(result),
        "already_had_address": statuses.count("existing"),
        "geocoded": statuses.count("ok"),
        "not_found": statuses.count("not_found"),
        "invalid_coords": statuses.count("invalid_coords"),
        "by_provider": dict(by_provider),
    }
