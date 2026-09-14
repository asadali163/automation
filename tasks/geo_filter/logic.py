"""Pure logic for the Geo Boundary Filter task — no Streamlit here.

Pipeline: parse_kml_boundary -> filter_points_in_boundary
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

_KML_NS = "{http://www.opengis.net/kml/2.2}"


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


def filter_points_in_boundary(
    df: pd.DataFrame, lat_col: str, lon_col: str, boundary
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """Split `df` into (inside, outside) based on whether each row's
    (lat_col, lon_col) point falls within/on `boundary`. Rows with
    non-numeric or missing coordinates count as outside and are reported
    separately in the stats.
    """
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    valid = lat.notna() & lon.notna()

    inside_mask = pd.Series(False, index=df.index)
    for idx in df.index[valid]:
        point = Point(lon.loc[idx], lat.loc[idx])
        inside_mask.loc[idx] = boundary.covers(point)

    inside_df = df.loc[inside_mask].reset_index(drop=True)
    outside_df = df.loc[~inside_mask].reset_index(drop=True)

    stats = {
        "total_rows": len(df),
        "invalid_coords": int((~valid).sum()),
        "inside": int(inside_mask.sum()),
        "outside": int((~inside_mask).sum()),
    }
    return inside_df, outside_df, stats
