"""Pure logic for the Geocoding task — no Streamlit here.

Two providers, tried in order per address:

1. **Nominatim** (OpenStreetMap) — free, no key. Queried through a ladder of
   progressively simpler variants of the address (raw -> district marker
   stripped -> house-number range/suffix simplified -> street only), which is
   what lifts the hit rate dramatically on messy official-register addresses.
   Rate-limited to ~1 req/sec per Nominatim's usage policy.
2. **Geoapify** — used only for the addresses Nominatim couldn't resolve, so
   it burns very few of the free tier's 3,000 requests/day.

Identical addresses are only looked up once per run (cached).
"""
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "Automation-Project/1.0 (personal data automation project)"}
NOMINATIM_DELAY = 1.1  # Nominatim usage policy: max 1 req/sec

GEOAPIFY_URL = "https://api.geoapify.com/v1/geocode/search"
DAILY_REQUEST_LIMIT = 3000  # Geoapify free-tier cap

PROVIDER_NOMINATIM = "nominatim"
PROVIDER_GEOAPIFY = "geoapify"


@dataclass(frozen=True)
class GeocodeHit:
    latitude: float
    longitude: float
    provider: str      # which service resolved it
    query_used: str     # the address variant that actually worked


GeocodeFn = Callable[[str], Optional[GeocodeHit]]


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
                NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS, timeout=timeout
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
            GEOAPIFY_URL,
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


def chain_providers(providers: List[GeocodeFn]) -> GeocodeFn:
    """Try each provider in order; the first hit wins.

    A provider that raises (network error, rate limit, bad key) is skipped so
    the next one still gets its turn — an outage in the primary degrades to
    the fallback instead of failing the row.
    """

    def geocode(address: str) -> Optional[GeocodeHit]:
        for provider in providers:
            try:
                hit = provider(address)
            except Exception:  # noqa: BLE001 - provider failed, fall through to the next
                continue
            if hit is not None:
                return hit
        return None

    return geocode


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
    """Counts for the run: totals, per-status and per-provider breakdown."""
    statuses = list(result["geocode_status"])
    by_provider = Counter(s for s in result["geocode_source"] if s)
    return {
        "total_rows": len(result),
        "geocoded": statuses.count("ok"),
        "not_found": statuses.count("not_found"),
        "empty_address": statuses.count("empty_address"),
        "by_provider": dict(by_provider),
    }
