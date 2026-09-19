"""Pure logic for the Geo Boundary Filter task — no Streamlit here.

Pipeline: parse_kml_boundary -> filter_points_in_boundary -> split_by_status
"""
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from shapely.geometry import Point, Polygon, mapping
from shapely.ops import unary_union

_KML_NS = "{http://www.opengis.net/kml/2.2}"

STATUS_INBOUND = "inbound"    # inside the boundary
STATUS_OUTBOUND = "outbound"   # outside the boundary (or coordinates missing/invalid)

STATUS_COLORS = {
    STATUS_INBOUND: [34, 139, 34, 200],    # forest green
    STATUS_OUTBOUND: [220, 20, 60, 200],    # crimson
}


def _local_tag(tag: str) -> str:
    """Strip any XML namespace prefix, e.g. '{...}Polygon' -> 'Polygon'."""
    return tag.rsplit("}", 1)[-1]


def _parse_coordinates(text: str) -> List[Tuple[float, float]]:
    """KML <coordinates> text is whitespace-separated 'lon,lat[,alt]' tuples."""
    points = []
    for chunk in text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        points.append((lon, lat))
    return points


def parse_kml_boundary(path: Path):
    """Parse every <Polygon> in a KML file into one combined shapely
    geometry (outer ring minus any inner holes), unioning multiple
    polygons together if the file defines more than one boundary shape.
    Namespace-agnostic, since real-world KML exports vary.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    polygons = []
    for elem in root.iter():
        if _local_tag(elem.tag) != "Polygon":
            continue

        outer_coords = None
        holes = []
        for child in elem.iter():
            tag = _local_tag(child.tag)
            if tag == "outerBoundaryIs":
                for coord_elem in child.iter():
                    if _local_tag(coord_elem.tag) == "coordinates" and coord_elem.text:
                        outer_coords = _parse_coordinates(coord_elem.text)
            elif tag == "innerBoundaryIs":
                for coord_elem in child.iter():
                    if _local_tag(coord_elem.tag) == "coordinates" and coord_elem.text:
                        holes.append(_parse_coordinates(coord_elem.text))

        if outer_coords and len(outer_coords) >= 3:
            polygons.append(Polygon(outer_coords, holes))

    if not polygons:
        raise ValueError("No <Polygon> boundary found in this KML file.")

    return unary_union(polygons)


def filter_points_in_boundary(df: pd.DataFrame, lat_col: str, lon_col: str, boundary) -> Tuple[pd.DataFrame, Dict]:
    """Add a `boundary_status` column ("inbound"/"outbound") to a copy of
    `df`, based on whether each row's (lat_col, lon_col) point falls
    within/on `boundary`. Rows with non-numeric or missing coordinates
    count as outbound (there's no way to place them), and are reported
    separately in the stats so they're not silently conflated with
    genuinely-outside rows.
    """
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    valid = lat.notna() & lon.notna()

    inside_mask = pd.Series(False, index=df.index)
    for idx in df.index[valid]:
        point = Point(lon.loc[idx], lat.loc[idx])
        inside_mask.loc[idx] = boundary.covers(point)

    processed = df.copy()
    processed["boundary_status"] = [STATUS_INBOUND if v else STATUS_OUTBOUND for v in inside_mask]

    stats = {
        "total_rows": len(df),
        "invalid_coords": int((~valid).sum()),
        "inbound": int(inside_mask.sum()),
        "outbound": int((~inside_mask).sum()),
    }
    return processed, stats


def split_by_status(processed: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split a `filter_points_in_boundary` result into (inbound_df, outbound_df)."""
    inbound = processed.loc[processed["boundary_status"] == STATUS_INBOUND].reset_index(drop=True)
    outbound = processed.loc[processed["boundary_status"] == STATUS_OUTBOUND].reset_index(drop=True)
    return inbound, outbound


def boundary_to_geojson_feature(boundary) -> Dict:
    """The boundary geometry as a GeoJSON Feature, ready for a map layer."""
    return {"type": "Feature", "properties": {}, "geometry": mapping(boundary)}


def compute_view_state(boundary) -> Tuple[float, float, int]:
    """A (latitude, longitude, zoom) reasonable for framing `boundary` on a
    map — centered on its centroid, zoomed to roughly fit its extent.
    """
    centroid = boundary.centroid
    min_lon, min_lat, max_lon, max_lat = boundary.bounds
    span = max(max_lon - min_lon, max_lat - min_lat, 1e-6)
    zoom = max(2, min(16, round(8 - math.log2(span))))
    return centroid.y, centroid.x, zoom


def build_detail_fields(display_columns: List[str]) -> List[Tuple[str, str]]:
    """Map each display column to a template-safe key ("field0", "field1",
    ...), paired with its original name as the human-readable label.

    Used for the map's hover tooltip and click-details panel: pydeck/deck.gl
    templates substitute `{key}` directly against a data point's properties,
    so real column names (which may contain spaces or other characters) are
    kept only as labels, never as the template key itself.
    """
    return [(f"field{i}", str(col)) for i, col in enumerate(display_columns)]
