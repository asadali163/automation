from typing import List, Optional

import pandas as pd

from tasks.geocoding import logic


def _hit(lat: float, lon: float, provider: str, query: str) -> logic.GeocodeHit:
    return logic.GeocodeHit(latitude=lat, longitude=lon, provider=provider, query_used=query)


# --- address normalisation ladder -------------------------------------------------


def test_strip_district_removes_hungarian_district_marker():
    assert (
        logic.strip_district("1071 Budapest 07. ker. Rottenbiller utca 49.")
        == "1071 Budapest Rottenbiller utca 49."
    )


def test_strip_district_leaves_other_addresses_untouched():
    assert logic.strip_district("1031 Budapest, Nánási út 24/A.") == "1031 Budapest, Nánási út 24/A."


def test_simplify_house_number_takes_first_of_range_and_drops_suffix():
    assert logic.simplify_house_number("Zsókavár utca 43-47 fszt") == "Zsókavár utca 43."


def test_street_only_drops_house_number_but_keeps_street():
    assert (
        logic.street_only("1071 Budapest Rottenbiller utca 49.") == "1071 Budapest Rottenbiller utca"
    )
    assert logic.street_only("1031 Budapest, Nánási út 24/A.") == "1031 Budapest, Nánási út"


def test_build_candidates_is_ordered_and_deduplicated():
    candidates = logic.build_candidates("1071 Budapest 07. ker. Rottenbiller utca 49.")

    assert candidates[0] == "1071 Budapest 07. ker. Rottenbiller utca 49."  # raw first
    assert "1071 Budapest Rottenbiller utca 49." in candidates  # district stripped
    assert len(candidates) == len(set(candidates))  # no repeats


def test_build_candidates_collapses_to_one_when_nothing_to_simplify():
    # a clean address yields fewer distinct variants
    candidates = logic.build_candidates("Main Street")
    assert candidates == ["Main Street"]


# --- provider chaining ------------------------------------------------------------


def test_chain_providers_uses_first_provider_when_it_resolves():
    calls: List[str] = []

    def primary(address: str) -> Optional[logic.GeocodeHit]:
        calls.append("primary")
        return _hit(1.0, 2.0, "nominatim", address)

    def fallback(address: str) -> Optional[logic.GeocodeHit]:
        calls.append("fallback")
        return _hit(9.9, 9.9, "geoapify", address)

    hit = logic.chain_providers([primary, fallback])("somewhere")

    assert hit == _hit(1.0, 2.0, "nominatim", "somewhere")
    assert calls == ["primary"]  # fallback never invoked


def test_chain_providers_falls_back_when_primary_finds_nothing():
    def primary(address: str) -> Optional[logic.GeocodeHit]:
        return None

    def fallback(address: str) -> Optional[logic.GeocodeHit]:
        return _hit(9.9, 8.8, "geoapify", address)

    hit = logic.chain_providers([primary, fallback])("hard address")

    assert hit is not None
    assert hit.provider == "geoapify"
    assert (hit.latitude, hit.longitude) == (9.9, 8.8)


def test_chain_providers_falls_back_when_primary_raises():
    def primary(address: str) -> Optional[logic.GeocodeHit]:
        raise RuntimeError("nominatim is down")

    def fallback(address: str) -> Optional[logic.GeocodeHit]:
        return _hit(5.0, 6.0, "geoapify", address)

    hit = logic.chain_providers([primary, fallback])("anything")

    assert hit is not None and hit.provider == "geoapify"


def test_chain_providers_returns_none_when_every_provider_fails():
    assert logic.chain_providers([lambda a: None, lambda a: None])("nowhere") is None


# --- dataframe driver -------------------------------------------------------------


def test_build_queries_joins_selected_columns_skipping_blanks():
    df = pd.DataFrame(
        {
            "street": ["10 Downing Street", "", "Eiffel Tower"],
            "city": ["London", "Nowhere", "Paris"],
        }
    )
    queries = logic.build_queries(df, ["street", "city"])
    assert list(queries) == ["10 Downing Street, London", "Nowhere", "Eiffel Tower, Paris"]


def test_count_unique_queries_dedupes_and_ignores_blank():
    df = pd.DataFrame({"address": ["a", "a", "", "b"]})
    assert logic.count_unique_queries(df, ["address"]) == 2


def test_geocode_dataframe_records_provider_and_caches_repeats():
    df = pd.DataFrame({"address": ["easy", "easy", "hard", "nowhere", ""]})
    calls: List[str] = []

    def geocode(address: str) -> Optional[logic.GeocodeHit]:
        calls.append(address)
        if address == "easy":
            return _hit(1.0, 2.0, "nominatim", "easy")
        if address == "hard":
            return _hit(3.0, 4.0, "geoapify", "hard")
        return None

    result = logic.geocode_dataframe(df, ["address"], geocode_fn=geocode)

    assert list(result["geocode_status"]) == ["ok", "ok", "ok", "not_found", "empty_address"]
    assert list(result["geocode_source"]) == ["nominatim", "nominatim", "geoapify", "", ""]
    assert calls.count("easy") == 1  # second occurrence served from cache

    stats = logic.summarise(result)
    assert stats["total_rows"] == 5
    assert stats["geocoded"] == 3
    assert stats["not_found"] == 1
    assert stats["empty_address"] == 1
    assert stats["by_provider"] == {"nominatim": 2, "geoapify": 1}


def test_geocode_dataframe_calls_progress_callback_for_every_row():
    df = pd.DataFrame({"address": ["a", "b", "c"]})
    progress_calls = []

    logic.geocode_dataframe(
        df,
        ["address"],
        geocode_fn=lambda a: None,
        progress_callback=lambda done, total: progress_calls.append((done, total)),
    )

    assert progress_calls == [(1, 3), (2, 3), (3, 3)]


# --- HTTP-level provider behaviour (requests mocked) ------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_nominatim_fn_walks_candidates_until_one_resolves(monkeypatch):
    queries_seen = []

    def fake_get(url, params, headers, timeout):
        queries_seen.append(params["q"])
        # only the district-stripped variant resolves
        if params["q"] == "1071 Budapest Rottenbiller utca 49.":
            return _FakeResponse([{"lat": "47.5", "lon": "19.07"}])
        return _FakeResponse([])

    monkeypatch.setattr(logic.requests, "get", fake_get)
    monkeypatch.setattr(logic.time, "sleep", lambda s: None)  # don't actually wait

    geocode = logic.build_nominatim_fn(country_code="hu")
    hit = geocode("1071 Budapest 07. ker. Rottenbiller utca 49.")

    assert hit is not None
    assert (hit.latitude, hit.longitude) == (47.5, 19.07)
    assert hit.provider == logic.PROVIDER_NOMINATIM
    assert hit.query_used == "1071 Budapest Rottenbiller utca 49."
    assert queries_seen[0] == "1071 Budapest 07. ker. Rottenbiller utca 49."  # raw tried first


def test_nominatim_fn_passes_country_code_when_given(monkeypatch):
    captured = {}

    def fake_get(url, params, headers, timeout):
        captured.update(params)
        return _FakeResponse([{"lat": "1", "lon": "2"}])

    monkeypatch.setattr(logic.requests, "get", fake_get)
    monkeypatch.setattr(logic.time, "sleep", lambda s: None)

    logic.build_nominatim_fn(country_code="hu")("somewhere")
    assert captured["countrycodes"] == "hu"
    assert captured["format"] == "json"


def test_nominatim_fn_omits_country_code_when_blank(monkeypatch):
    captured = {}

    def fake_get(url, params, headers, timeout):
        captured.update(params)
        return _FakeResponse([{"lat": "1", "lon": "2"}])

    monkeypatch.setattr(logic.requests, "get", fake_get)
    monkeypatch.setattr(logic.time, "sleep", lambda s: None)

    logic.build_nominatim_fn()("somewhere")
    assert "countrycodes" not in captured


def test_geoapify_fn_parses_response(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured.update(params)
        assert url == logic.GEOAPIFY_URL
        return _FakeResponse({"results": [{"formatted": "Somewhere", "lat": 1.23, "lon": 4.56}]})

    monkeypatch.setattr(logic.requests, "get", fake_get)

    hit = logic.build_geoapify_fn(api_key="test-key")("Somewhere, Nowhere")

    assert hit is not None
    assert (hit.latitude, hit.longitude) == (1.23, 4.56)
    assert hit.provider == logic.PROVIDER_GEOAPIFY
    assert captured == {
        "text": "Somewhere, Nowhere",
        "apiKey": "test-key",
        "format": "json",
        "limit": 1,
    }


def test_geoapify_fn_returns_none_when_no_results(monkeypatch):
    monkeypatch.setattr(
        logic.requests, "get", lambda url, params, timeout: _FakeResponse({"results": []})
    )
    assert logic.build_geoapify_fn(api_key="k")("nowhere at all") is None
