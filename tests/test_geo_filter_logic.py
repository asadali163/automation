from pathlib import Path

import pandas as pd
import pytest

from tasks.geo_filter import logic

# A 10x10 degree square boundary: lon in [0,10], lat in [0,10].
# KML coordinates are "lon,lat[,alt]" order.
_SQUARE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Square</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              0,0,0 0,10,0 10,10,0 10,0,0 0,0,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""

# Same square but with a namespace-free root tag, mimicking KML exports
# that omit the default xmlns.
_SQUARE_KML_NO_NS = _SQUARE_KML.replace(' xmlns="http://www.opengis.net/kml/2.2"', "")


def _write_kml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "boundary.kml"
    path.write_text(content)
    return path


@pytest.mark.parametrize("kml_content", [_SQUARE_KML, _SQUARE_KML_NO_NS])
def test_parse_kml_boundary_covers_expected_area(tmp_path, kml_content):
    from shapely.geometry import Point

    boundary = logic.parse_kml_boundary(_write_kml(tmp_path, kml_content))

    assert boundary.covers(Point(5, 5))       # well inside
    assert boundary.covers(Point(0, 0))        # on the corner
    assert not boundary.covers(Point(20, 20))    # well outside


def test_parse_kml_boundary_raises_when_no_polygon(tmp_path):
    path = _write_kml(tmp_path, '<?xml version="1.0"?><kml></kml>')
    with pytest.raises(ValueError, match="No <Polygon>"):
        logic.parse_kml_boundary(path)


def test_filter_points_in_boundary_labels_rows_and_reports_stats(tmp_path):
    boundary = logic.parse_kml_boundary(_write_kml(tmp_path, _SQUARE_KML))

    df = pd.DataFrame(
        {
            "Shop": ["Inside Shop", "Outside Shop", "Edge Shop", "Bad Coords Shop"],
            "Latitude": ["5", "50", "0", "not-a-number"],
            "Longitude": ["5", "50", "0", "5"],
        }
    )

    processed, stats = logic.filter_points_in_boundary(
        df, lat_col="Latitude", lon_col="Longitude", boundary=boundary
    )

    assert stats["total_rows"] == 4
    assert stats["invalid_coords"] == 1
    assert stats["inbound"] == 2   # Inside Shop + Edge Shop
    assert stats["outbound"] == 2   # Outside Shop + Bad Coords Shop

    # processed keeps every original row, in order, plus the new column
    assert list(processed["Shop"]) == ["Inside Shop", "Outside Shop", "Edge Shop", "Bad Coords Shop"]
    assert list(processed["boundary_status"]) == [
        logic.STATUS_INBOUND,
        logic.STATUS_OUTBOUND,
        logic.STATUS_INBOUND,
        logic.STATUS_OUTBOUND,
    ]


def test_split_by_status_separates_inbound_and_outbound(tmp_path):
    boundary = logic.parse_kml_boundary(_write_kml(tmp_path, _SQUARE_KML))
    df = pd.DataFrame(
        {
            "Shop": ["Inside Shop", "Outside Shop", "Bad Coords Shop"],
            "Latitude": ["5", "50", "not-a-number"],
            "Longitude": ["5", "50", "5"],
        }
    )
    processed, _ = logic.filter_points_in_boundary(df, "Latitude", "Longitude", boundary)

    inbound_df, outbound_df = logic.split_by_status(processed)

    assert list(inbound_df["Shop"]) == ["Inside Shop"]
    assert list(outbound_df["Shop"]) == ["Outside Shop", "Bad Coords Shop"]
    assert (inbound_df["boundary_status"] == logic.STATUS_INBOUND).all()
    assert (outbound_df["boundary_status"] == logic.STATUS_OUTBOUND).all()


def test_boundary_to_geojson_feature_wraps_geometry(tmp_path):
    boundary = logic.parse_kml_boundary(_write_kml(tmp_path, _SQUARE_KML))

    feature = logic.boundary_to_geojson_feature(boundary)

    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_compute_view_state_centers_on_boundary(tmp_path):
    boundary = logic.parse_kml_boundary(_write_kml(tmp_path, _SQUARE_KML))

    lat, lon, zoom = logic.compute_view_state(boundary)

    # the 10x10 square spans lon/lat [0,10] -> centroid at (5, 5)
    assert lat == pytest.approx(5, abs=0.01)
    assert lon == pytest.approx(5, abs=0.01)
    assert 2 <= zoom <= 16
