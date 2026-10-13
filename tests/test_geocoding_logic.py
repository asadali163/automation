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


# --- reverse geocoding (coordinates -> address) -----------------------------------


def _reverse_hit(address: str, provider: str) -> logic.ReverseHit:
    return logic.ReverseHit(address=address, provider=provider)


def test_nominatim_reverse_fn_parses_display_name(monkeypatch):
    captured = {}

    def fake_get(url, params, headers, timeout):
        captured.update(params)
        assert url == logic.NOMINATIM_REVERSE_URL
        return _FakeResponse({"display_name": "10 Downing Street, London, UK"})

    monkeypatch.setattr(logic.requests, "get", fake_get)
    monkeypatch.setattr(logic.time, "sleep", lambda s: None)

    hit = logic.build_nominatim_reverse_fn()(51.5034, -0.1276)

    assert hit == _reverse_hit("10 Downing Street, London, UK", logic.PROVIDER_NOMINATIM)
    assert captured == {"lat": 51.5034, "lon": -0.1276, "format": "json"}


def test_nominatim_reverse_fn_returns_none_when_no_display_name(monkeypatch):
    monkeypatch.setattr(logic.requests, "get", lambda url, params, headers, timeout: _FakeResponse({}))
    monkeypatch.setattr(logic.time, "sleep", lambda s: None)

    assert logic.build_nominatim_reverse_fn()(0.0, 0.0) is None


def test_geoapify_reverse_fn_parses_formatted_address(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured.update(params)
        assert url == logic.GEOAPIFY_REVERSE_URL
        return _FakeResponse({"results": [{"formatted": "Eiffel Tower, Paris, France"}]})

    monkeypatch.setattr(logic.requests, "get", fake_get)

    hit = logic.build_geoapify_reverse_fn(api_key="test-key")(48.8584, 2.2945)

    assert hit == _reverse_hit("Eiffel Tower, Paris, France", logic.PROVIDER_GEOAPIFY)
    assert captured == {"lat": 48.8584, "lon": 2.2945, "apiKey": "test-key", "format": "json"}


def test_geoapify_reverse_fn_returns_none_when_no_results(monkeypatch):
    monkeypatch.setattr(
        logic.requests, "get", lambda url, params, timeout: _FakeResponse({"results": []})
    )
    assert logic.build_geoapify_reverse_fn(api_key="k")(0.0, 0.0) is None


def test_chain_providers_works_for_reverse_signature_too():
    def primary(lat, lon):
        return None

    def fallback(lat, lon):
        return _reverse_hit("fallback address", logic.PROVIDER_GEOAPIFY)

    hit = logic.chain_providers([primary, fallback])(1.0, 2.0)

    assert hit == _reverse_hit("fallback address", logic.PROVIDER_GEOAPIFY)


def test_count_unique_coords_dedupes_and_ignores_invalid():
    df = pd.DataFrame(
        {
            "lat": ["1.0", "1.0000001", "2.0", "not-a-number"],
            "lon": ["3.0", "3.0000001", "4.0", "5.0"],
        }
    )
    # the first two rows round to the same (1.0, 3.0) pair at 6 decimals
    assert logic.count_unique_coords(df, "lat", "lon") == 2


def test_reverse_geocode_dataframe_adds_columns_and_caches_repeats():
    df = pd.DataFrame(
        {
            "lat": ["51.5034", "51.5034", "0.0", "bad"],
            "lon": ["-0.1276", "-0.1276", "0.0", "5.0"],
        }
    )
    calls: List[tuple] = []

    def reverse_fn(lat: float, lon: float) -> Optional[logic.ReverseHit]:
        calls.append((lat, lon))
        if (lat, lon) == (51.5034, -0.1276):
            return _reverse_hit("10 Downing Street", logic.PROVIDER_NOMINATIM)
        return None

    result = logic.reverse_geocode_dataframe(df, "lat", "lon", reverse_fn)

    assert list(result["reverse_address"]) == ["10 Downing Street", "10 Downing Street", "", ""]
    assert list(result["reverse_geocode_status"]) == ["ok", "ok", "not_found", "invalid_coords"]
    assert list(result["reverse_geocode_source"]) == [
        logic.PROVIDER_NOMINATIM,
        logic.PROVIDER_NOMINATIM,
        "",
        "",
    ]
    assert calls.count((51.5034, -0.1276)) == 1  # second occurrence served from cache

    stats = logic.summarise_reverse(result)
    assert stats == {
        "total_rows": 4,
        "already_had_address": 0,
        "geocoded": 2,
        "not_found": 1,
        "invalid_coords": 1,
        "by_provider": {logic.PROVIDER_NOMINATIM: 2},
    }


def test_reverse_geocode_dataframe_calls_progress_callback_for_every_row():
    df = pd.DataFrame({"lat": ["1", "2"], "lon": ["1", "2"]})
    progress_calls = []

    logic.reverse_geocode_dataframe(
        df,
        "lat",
        "lon",
        reverse_fn=lambda lat, lon: None,
        progress_callback=lambda done, total: progress_calls.append((done, total)),
    )

    assert progress_calls == [(1, 2), (2, 2)]


def test_reverse_geocode_dataframe_does_not_overwrite_existing_address_column():
    df = pd.DataFrame({"address": ["Original Address"], "lat": ["1.0"], "lon": ["2.0"]})

    result = logic.reverse_geocode_dataframe(df, "lat", "lon", reverse_fn=lambda lat, lon: None)

    assert result["address"].iloc[0] == "Original Address"
    assert "reverse_address" in result.columns


def test_missing_value_mask_catches_nan_blank_whitespace_and_literal_nan_string():
    series = pd.Series([None, "", "   ", "nan", "NaN", "Real Address"])
    assert list(logic.missing_value_mask(series)) == [True, True, True, True, True, False]


def test_reverse_geocode_dataframe_with_address_col_only_fills_blanks(monkeypatch):
    # 1000-row-style scenario, scaled down: most rows already have an
    # address, only a few are blank.
    df = pd.DataFrame(
        {
            "Address": ["123 Existing St", "", "456 Existing Ave", None, "   "],
            "lat": ["1.0", "2.0", "3.0", "4.0", "5.0"],
            "lon": ["1.0", "2.0", "3.0", "4.0", "5.0"],
        }
    )
    calls: List[tuple] = []

    def reverse_fn(lat, lon):
        calls.append((lat, lon))
        return _reverse_hit(f"Resolved {lat},{lon}", logic.PROVIDER_NOMINATIM)

    result = logic.reverse_geocode_dataframe(df, "lat", "lon", reverse_fn, address_col="Address")

    # only the 3 blank rows ever reach the geocoder
    assert len(calls) == 3
    assert set(calls) == {(2.0, 2.0), (4.0, 4.0), (5.0, 5.0)}

    # untouched rows keep their exact original value, in the SAME column
    assert list(result["Address"]) == [
        "123 Existing St",
        "Resolved 2.0,2.0",
        "456 Existing Ave",
        "Resolved 4.0,4.0",
        "Resolved 5.0,5.0",
    ]
    assert "reverse_address" not in result.columns  # filled in place, no extra column
    assert list(result["reverse_geocode_status"]) == ["existing", "ok", "existing", "ok", "ok"]


def test_reverse_geocode_dataframe_address_col_not_present_falls_back_to_new_column():
    df = pd.DataFrame({"lat": ["1.0"], "lon": ["2.0"]})

    result = logic.reverse_geocode_dataframe(
        df, "lat", "lon", reverse_fn=lambda lat, lon: _reverse_hit("X", logic.PROVIDER_NOMINATIM),
        address_col="Address",  # doesn't exist in df
    )

    assert "reverse_address" in result.columns
    assert result["reverse_address"].iloc[0] == "X"


def test_count_unique_coords_excludes_rows_that_already_have_an_address():
    df = pd.DataFrame(
        {
            "Address": ["Known", "", "Known", ""],
            "lat": ["1.0", "2.0", "1.0", "2.0"],
            "lon": ["1.0", "2.0", "1.0", "2.0"],
        }
    )
    # without address_col: all 2 distinct pairs count
    assert logic.count_unique_coords(df, "lat", "lon") == 2
    # with address_col: only the blank rows' pair (2.0, 2.0) counts
    assert logic.count_unique_coords(df, "lat", "lon", address_col="Address") == 1


def test_reverse_geocode_dataframe_skips_api_entirely_when_nothing_is_blank():
    df = pd.DataFrame({"Address": ["A", "B"], "lat": ["1.0", "2.0"], "lon": ["1.0", "2.0"]})

    def reverse_fn(lat, lon):
        raise AssertionError("should never be called when nothing is blank")

    result = logic.reverse_geocode_dataframe(df, "lat", "lon", reverse_fn, address_col="Address")

    assert list(result["Address"]) == ["A", "B"]
    assert list(result["reverse_geocode_status"]) == ["existing", "existing"]
