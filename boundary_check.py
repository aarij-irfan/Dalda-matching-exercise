"""
City boundary checks using Boudaries/*.geojson (district polygons).
Outlets >5 km outside their city's boundary are flagged.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.ops import nearest_points

from matching_engine import haversine_distance

TARGET_CITIES = (
    "Faisalabad",
    "Gujranwala",
    "Karachi",
    "Lahore",
    "Multan",
    "Peshawar",
)

DEFAULT_BUFFER_KM = 5.0
CITY_COLUMN_HINTS = ("city", "city name", "town", "city_name", "district")


@dataclass
class BoundaryCheckResult:
    boundary_city_col: str | None
    buffer_km: float
    outside_boundary_count: int
    inside_or_within_buffer_count: int
    unknown_city_count: int
    no_boundary_for_city_count: int
    by_city: dict[str, dict[str, int]]
    assigned_city: list[str]
    distance_outside_m: list[float]
    boundary_status: list[str]


def default_boundaries_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "Boudaries", "Districts_simplified.geojson")


def _normalize_city_name(name: str) -> str:
    if not name or pd.isna(name):
        return ""
    s = str(name).strip()
    s = re.sub(r"\s+", " ", s)
    # Common variants
    aliases = {
        "fsd": "Faisalabad",
        "lhe": "Lahore",
        "khi": "Karachi",
        "karachi city": "Karachi",
        "lahore city": "Lahore",
    }
    low = s.lower()
    if low in aliases:
        return aliases[low]
    return s.title() if s.isupper() or s.islower() else s


def detect_city_column(columns: list[str]) -> str | None:
    normalized = {re.sub(r"\s+", " ", c.strip().lower()): c for c in columns}
    for hint in CITY_COLUMN_HINTS:
        for norm, original in normalized.items():
            if hint in norm.split() or norm == hint:
                return original
    return None


def load_city_boundaries(
    geojson_path: str | None = None,
    cities: tuple[str, ...] = TARGET_CITIES,
) -> dict[str, object]:
    path = geojson_path or default_boundaries_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Boundary file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    boundaries: dict[str, object] = {}
    city_lower = {c.lower(): c for c in cities}

    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name = props.get("shapeName") or props.get("NAME") or props.get("name") or ""
        key = city_lower.get(str(name).strip().lower())
        if key:
            boundaries[key] = shape(feat["geometry"])

    missing = [c for c in cities if c not in boundaries]
    if missing:
        raise ValueError(f"Missing boundary polygons for: {', '.join(missing)}")
    return boundaries


def _distance_meters_to_polygon(lat: float, lon: float, polygon) -> float:
    pt = Point(lon, lat)
    if polygon.contains(pt):
        return 0.0
    nearest_pt = nearest_points(pt, polygon)[1]
    return haversine_distance(lat, lon, nearest_pt.y, nearest_pt.x)


def _resolve_row_city(row: pd.Series, city_col: str | None, boundaries: dict) -> str:
    if city_col and city_col in row.index:
        raw = row.get(city_col)
        if pd.notna(raw) and str(raw).strip():
            norm = _normalize_city_name(str(raw))
            for c in boundaries:
                if norm.lower() == c.lower():
                    return c
            return norm  # unknown name

    # No city column or empty: assign by point-in-polygon
    return ""


def check_boundaries(
    df: pd.DataFrame,
    latitudes: list,
    longitudes: list,
    gps_statuses: list[str],
    city_col: str | None = None,
    buffer_km: float = DEFAULT_BUFFER_KM,
    geojson_path: str | None = None,
) -> BoundaryCheckResult:
    boundaries = load_city_boundaries(geojson_path)
    city_col = city_col or detect_city_column(list(df.columns))
    buffer_m = buffer_km * 1000.0
    n = len(df)

    assigned_city: list[str] = []
    distance_outside_m: list[float] = []
    boundary_status: list[str] = []

    by_city: dict[str, dict[str, int]] = {c: {"ok": 0, "outside": 0, "skipped": 0} for c in TARGET_CITIES}
    outside_count = 0
    ok_count = 0
    unknown_city_count = 0
    no_boundary_count = 0

    for i in range(n):
        if gps_statuses[i] != "ok":
            assigned_city.append("")
            distance_outside_m.append(np.nan)
            boundary_status.append("skipped_bad_gps")
            continue

        lat, lon = latitudes[i], longitudes[i]
        row = df.iloc[i]
        city = _resolve_row_city(row, city_col, boundaries)

        if not city:
            # Try which polygon contains the point
            pt = Point(lon, lat)
            found = []
            for cname, poly in boundaries.items():
                if poly.contains(pt):
                    found.append(cname)
            if len(found) == 1:
                city = found[0]
            elif len(found) > 1:
                city = found[0]
            else:
                # Nearest city by boundary distance
                best_c, best_d = None, float("inf")
                for cname, poly in boundaries.items():
                    d = _distance_meters_to_polygon(lat, lon, poly)
                    if d < best_d:
                        best_d, best_c = d, cname
                city = best_c or ""

        if city not in boundaries:
            assigned_city.append(city or "UNKNOWN")
            distance_outside_m.append(np.nan)
            boundary_status.append("unknown_city")
            unknown_city_count += 1
            continue

        dist_m = _distance_meters_to_polygon(lat, lon, boundaries[city])
        assigned_city.append(city)
        distance_outside_m.append(round(dist_m, 2))

        if dist_m <= buffer_m:
            boundary_status.append("within_buffer")
            ok_count += 1
            by_city[city]["ok"] += 1
        else:
            boundary_status.append("outside_boundary")
            outside_count += 1
            by_city[city]["outside"] += 1

    return BoundaryCheckResult(
        boundary_city_col=city_col,
        buffer_km=buffer_km,
        outside_boundary_count=outside_count,
        inside_or_within_buffer_count=ok_count,
        unknown_city_count=unknown_city_count,
        no_boundary_for_city_count=no_boundary_count,
        by_city=by_city,
        assigned_city=assigned_city,
        distance_outside_m=distance_outside_m,
        boundary_status=boundary_status,
    )


def save_boundary_map(
    df: pd.DataFrame,
    latitudes: list,
    longitudes: list,
    boundary_status: list[str],
    assigned_city: list[str],
    output_path: str,
    geojson_path: str | None = None,
    cities: tuple[str, ...] = TARGET_CITIES,
) -> str:
    """Plot city boundaries and outlets; save PNG."""
    import matplotlib.pyplot as plt

    boundaries = load_city_boundaries(geojson_path, cities)
    n_cities = len(cities)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    axes = axes.flatten()

    for ax, city in zip(axes, cities):
        poly = boundaries[city]
        xs, ys = poly.exterior.xy
        ax.plot(xs, ys, color="#333333", linewidth=1.2, label="Boundary")
        ax.fill(xs, ys, alpha=0.08, color="#4488cc")

        lats, lons, bad_lats, bad_lons = [], [], [], []
        for i in range(len(df)):
            if assigned_city[i] != city or pd.isna(latitudes[i]):
                continue
            if boundary_status[i] == "outside_boundary":
                bad_lats.append(latitudes[i])
                bad_lons.append(longitudes[i])
            elif boundary_status[i] == "within_buffer":
                lats.append(latitudes[i])
                lons.append(longitudes[i])

        ax.scatter(lons, lats, s=4, c="green", alpha=0.5, label="OK (≤5km)")
        ax.scatter(bad_lons, bad_lats, s=8, c="red", alpha=0.7, label=">5km outside")
        ax.set_title(f"{city} — outside: {len(bad_lats):,}")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.legend(loc="upper right", fontsize=7)
        ax.set_aspect("equal", adjustable="datalim")

    plt.suptitle("Dalda outlets vs city boundaries (5 km buffer)", fontsize=14)
    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close()
    return output_path
