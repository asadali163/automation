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


def test_filter_points_in_boundary_splits_and_reports_stats(tmp_path):
    boundary = logic.parse_kml_boundary(_write_kml(tmp_path, _SQUARE_KML))

    df = pd.DataFrame(
        {
            "Shop": ["Inside Shop", "Outside Shop", "Edge Shop", "Bad Coords Shop"],
            "Latitude": ["5", "50", "0", "not-a-number"],
            "Longitude": ["5", "50", "0", "5"],
        }
    )

    inside_df, outside_df, stats = logic.filter_points_in_boundary(
        df, lat_col="Latitude", lon_col="Longitude", boundary=boundary
    )

    assert stats["total_rows"] == 4
    assert stats["invalid_coords"] == 1
    assert stats["inside"] == 2   # Inside Shop + Edge Shop
    assert stats["outside"] == 2   # Outside Shop + Bad Coords Shop

    assert sorted(inside_df["Shop"]) == ["Edge Shop", "Inside Shop"]
    assert sorted(outside_df["Shop"]) == ["Bad Coords Shop", "Outside Shop"]
