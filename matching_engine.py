"""
Dalda outlet ↔ Access Retail census matching engine.
Adapted from Pepsi matching logic with spatial indexing for large census files.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from math import radians, cos, sin, asin, sqrt
from typing import Any, Callable

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

try:
    from sklearn.neighbors import BallTree

    HAS_BALLTREE = True
except ImportError:
    HAS_BALLTREE = False


EARTH_RADIUS_M = 6_371_000

# Column name hints for auto-detection (longer / specific hints first)
NAME_HINTS = (
    "name of outlet",
    "shop name",
    "store name",
    "outlet name",
    "customer name",
    "shop_name",
    "outlet_name",
)
LAT_HINTS = ("latitude", "lat")
LON_HINTS = ("longitude", "lng", "lon", "long")
GPS_HINTS = ("gps coordinates", "gps coordinate", "gps", "geo coordinates", "coordinates")
ADDRESS_HINTS = ("complete address", "full address", "address", "locality")
CHANNEL_HINTS = ("channel bucket", "channel type", "channel", "type of outlet", "outlet type")
SHOP_ID_HINTS = (
    "shop id",
    "shop_id",
    "shop code",
    "shop_code",
    "customer code",
    "customer_code",
    "outlet id",
    "outlet_id",
    "store id",
    "store code",
    "serial",
    "area id",
)

# Exact census column names (Access Retail Dalda export)
CENSUS_DEFAULTS = {
    "shop_id": "Serial",
    "shop_name": "Name of Outlet",
    "gps_combined": "GPS Coordinates",
    "address": "Complete Address Field",
    "channel": "Channel Bucket",
}

# Canonical output column names
DALDA_SHOP_ID_COL = "dalda_shop_id"
DALDA_OUTLET_NAME_COL = "dalda_outlet_name"
CENSUS_SHOP_ID_COL = "census_shop_id"
CENSUS_OUTLET_NAME_COL = "census_outlet_name"
MATCH_COLS = (
    "match_status",
    "match_score",
    "match_confidence",
    "match_distance_meters",
    "match_proximity_score",
    "match_name_score",
    "match_candidates_evaluated",
    "match_unmatched_reason",
)


@dataclass
class ColumnMapping:
    shop_id: str | None = None
    shop_name: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    gps_combined: str | None = None
    address: str | None = None
    channel: str | None = None


@dataclass
class MatchSettings:
    max_radius_m: float = 2000.0
    top_n_candidates: int = 100
    min_score_threshold: float = 40.0
    high_confidence_threshold: float = 70.0
    medium_confidence_threshold: float = 50.0
    proximity_weight: float = 40.0
    name_weight: float = 60.0
    worker_threads: int = 4


@dataclass
class MatchStats:
    total_dalda: int = 0
    matched: int = 0
    unmatched: int = 0
    below_threshold: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    average_score: float = 0.0
    average_distance_m: float = 0.0


def _normalize_col(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _hint_matches(norm_col: str, hint: str) -> bool:
    """Match hint as whole word(s), avoiding 'lat' in 'location' or 'y' in 'urbanity'."""
    if hint in norm_col:
        # Single-token hints must match a full column token
        if " " not in hint and len(hint) <= 4:
            tokens = re.split(r"[^a-z0-9]+", norm_col)
            return hint in tokens
        return True
    return False


def detect_column(columns: list[str], hints: tuple[str, ...]) -> str | None:
    normalized = {_normalize_col(c): c for c in columns}
    for hint in hints:
        for norm, original in normalized.items():
            if _hint_matches(norm, hint):
                return original
    return None


def _find_exact(columns: list[str], target: str) -> str | None:
    target_norm = _normalize_col(target)
    for c in columns:
        if _normalize_col(c) == target_norm:
            return c
    return None


def _column_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return slug or "column"


def dalda_output_key(source_col: str, mapping: ColumnMapping) -> str:
    if mapping.shop_id and source_col == mapping.shop_id:
        return DALDA_SHOP_ID_COL
    if mapping.shop_name and source_col == mapping.shop_name:
        return DALDA_OUTLET_NAME_COL
    return f"dalda_{_column_slug(source_col)}"


def census_output_key(source_col: str, mapping: ColumnMapping) -> str:
    if mapping.shop_id and source_col == mapping.shop_id:
        return CENSUS_SHOP_ID_COL
    if mapping.shop_name and source_col == mapping.shop_name:
        return CENSUS_OUTLET_NAME_COL
    return f"census_{_column_slug(source_col)}"


def suggest_column_mapping(columns: list[str], *, prefer_census_defaults: bool = False) -> ColumnMapping:
    if prefer_census_defaults:
        shop_id = _find_exact(columns, CENSUS_DEFAULTS["shop_id"])
        shop = _find_exact(columns, CENSUS_DEFAULTS["shop_name"])
        gps = _find_exact(columns, CENSUS_DEFAULTS["gps_combined"])
        addr = _find_exact(columns, CENSUS_DEFAULTS["address"])
        ch = _find_exact(columns, CENSUS_DEFAULTS["channel"])
        if shop or gps:
            return ColumnMapping(
                shop_id=shop_id or detect_column(columns, SHOP_ID_HINTS),
                shop_name=shop or detect_column(columns, NAME_HINTS),
                gps_combined=gps or detect_column(columns, GPS_HINTS),
                address=addr or detect_column(columns, ADDRESS_HINTS),
                channel=ch or detect_column(columns, CHANNEL_HINTS),
            )

    lat = detect_column(columns, LAT_HINTS)
    lon = detect_column(columns, LON_HINTS)
    gps = detect_column(columns, GPS_HINTS)
    if lat and lon:
        gps = None  # prefer separate lat/lon when both exist
    return ColumnMapping(
        shop_id=detect_column(columns, SHOP_ID_HINTS),
        shop_name=detect_column(columns, NAME_HINTS),
        latitude=lat,
        longitude=lon,
        gps_combined=gps,
        address=detect_column(columns, ADDRESS_HINTS),
        channel=detect_column(columns, CHANNEL_HINTS),
    )


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * asin(sqrt(a)) * EARTH_RADIUS_M


def parse_gps_value(value: Any) -> tuple[float | None, float | None]:
    if pd.isna(value) or value == "":
        return None, None
    text = str(value).strip()
    for sep in (",", ";", " "):
        parts = [p.strip() for p in text.split(sep) if p.strip()]
        if len(parts) >= 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return lat, lon
            except ValueError:
                continue
    return None, None


def normalize_text(text: Any) -> str:
    if pd.isna(text) or text == "":
        return ""
    text = str(text).upper().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[.,\-&]", " ", text)
    text = re.sub(r"\s+", " ", text)
    replacements = {
        "GENERAL STORE": "GEN STORE",
        "G STORE": "GEN STORE",
        "G.STORE": "GEN STORE",
        "GEN STORE": "GEN STORE",
        "GENERAL": "GEN STORE",
        "SUPER MART": "SUPERMART",
        "SUPERMARKET": "SUPERMART",
        "KIRYANA": "KIRYANA",
        "KIRANA": "KIRYANA",
        "SHOP": "STORE",
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
    words = [w for w in text.split() if w not in ("THE", "A", "AN")]
    return " ".join(words).strip()


def calculate_proximity_score(distance_m: float, max_weight: float = 40.0) -> float:
    scale = max_weight / 40.0
    if distance_m <= 25:
        return 40 * scale
    if distance_m <= 50:
        return 35 * scale
    if distance_m <= 100:
        return 30 * scale
    if distance_m <= 200:
        return 25 * scale
    if distance_m <= 300:
        return 22 * scale
    if distance_m <= 500:
        return 18 * scale
    if distance_m <= 750:
        return 14 * scale
    if distance_m <= 1000:
        return 10 * scale
    if distance_m <= 1500:
        return 6 * scale
    if distance_m <= 2000:
        return 3 * scale
    return max(0.0, 3 * scale - (distance_m - 2000) / 500 * scale)


def calculate_name_similarity(name1: Any, name2: Any, max_weight: float = 60.0) -> float:
    if pd.isna(name1) or pd.isna(name2):
        return 0.0
    norm1 = normalize_text(name1)
    norm2 = normalize_text(name2)
    if not norm1 or not norm2:
        return 0.0
    scale = max_weight / 60.0
    if norm1 == norm2:
        return 60 * scale
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    common = words1 & words2
    base_score = 0.0
    if common:
        overlap = len(common) / max(len(words1), len(words2))
        if overlap >= 0.5:
            base_score = (20 + (overlap - 0.5) * 40) * scale
        else:
            base_score = overlap * 40 * scale
    best_ratio = max(
        fuzz.ratio(norm1, norm2),
        fuzz.partial_ratio(norm1, norm2),
        fuzz.token_sort_ratio(norm1, norm2),
        fuzz.token_set_ratio(norm1, norm2),
    )
    if best_ratio >= 85:
        fuzzy_score = (35 + (best_ratio - 85) * 0.33) * scale
    elif best_ratio >= 70:
        fuzzy_score = (25 + (best_ratio - 70) * 0.67) * scale
    elif best_ratio >= 50:
        fuzzy_score = (15 + (best_ratio - 50) * 0.5) * scale
    elif best_ratio >= 30:
        fuzzy_score = (5 + (best_ratio - 30) * 0.5) * scale
    else:
        fuzzy_score = max(0.0, best_ratio * 0.17) * scale
    return max(base_score, fuzzy_score)


def confidence_level(score: float, settings: MatchSettings) -> str:
    if score >= settings.high_confidence_threshold:
        return "High"
    if score >= settings.medium_confidence_threshold:
        return "Medium"
    return "Low"


def load_table(path: str) -> pd.DataFrame:
    lower = path.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    if lower.endswith((".xlsx", ".xls", ".xlsm")):
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file type: {path}")


def list_census_files(census_dir: str) -> list[str]:
    import os

    if not os.path.isdir(census_dir):
        return []
    exts = (".csv", ".xlsx", ".xls", ".xlsm")
    files = []
    for name in sorted(os.listdir(census_dir)):
        if name.lower().endswith(exts):
            files.append(os.path.join(census_dir, name))
    return files


def _resolve_coords(
    row: pd.Series,
    mapping: ColumnMapping,
) -> tuple[float | None, float | None]:
    lat_col, lon_col, gps_col = mapping.latitude, mapping.longitude, mapping.gps_combined
    if lat_col and lon_col:
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
            if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0):
                return lat, lon
        except (TypeError, ValueError):
            pass
    if gps_col:
        return parse_gps_value(row.get(gps_col))
    return None, None


def _vectorized_parse_gps(series: pd.Series) -> pd.DataFrame:
    """Parse 'lat,lon' strings into two numeric columns."""
    extracted = series.astype(str).str.extract(
        r"^\s*([+-]?\d+\.?\d*)\s*[,;]\s*([+-]?\d+\.?\d*)", expand=True
    )
    extracted.columns = ["Latitude", "Longitude"]
    extracted["Latitude"] = pd.to_numeric(extracted["Latitude"], errors="coerce")
    extracted["Longitude"] = pd.to_numeric(extracted["Longitude"], errors="coerce")
    return extracted


def prepare_census_coordinates(
    census_df: pd.DataFrame,
    mapping: ColumnMapping | None = None,
) -> pd.DataFrame:
    """Ensure Latitude/Longitude columns exist on census data."""
    df = census_df.copy()
    mapping = mapping or suggest_column_mapping(
        list(df.columns), prefer_census_defaults=True
    )

    lat_col = mapping.latitude or ("Latitude" if "Latitude" in df.columns else None)
    lon_col = mapping.longitude or ("Longitude" if "Longitude" in df.columns else None)
    gps_col = mapping.gps_combined or detect_column(list(df.columns), GPS_HINTS)

    if lat_col and lat_col in df.columns:
        df["Latitude"] = pd.to_numeric(df[lat_col], errors="coerce")
    elif "Latitude" in df.columns:
        df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    else:
        df["Latitude"] = np.nan

    if lon_col and lon_col in df.columns:
        df["Longitude"] = pd.to_numeric(df[lon_col], errors="coerce")
    elif "Longitude" in df.columns:
        df["Longitude"] = pd.to_numeric(df[lon_col], errors="coerce")
    else:
        df["Longitude"] = np.nan

    need_gps = df["Latitude"].isna() | df["Longitude"].isna()
    if gps_col and gps_col in df.columns and need_gps.any():
        parsed = _vectorized_parse_gps(df.loc[need_gps, gps_col])
        df.loc[need_gps, "Latitude"] = df.loc[need_gps, "Latitude"].fillna(parsed["Latitude"])
        df.loc[need_gps, "Longitude"] = df.loc[need_gps, "Longitude"].fillna(
            parsed["Longitude"]
        )

    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    valid = (
        df["Latitude"].notna()
        & df["Longitude"].notna()
        & (df["Latitude"] != 0)
        & (df["Longitude"] != 0)
        & df["Latitude"].between(-90, 90)
        & df["Longitude"].between(-180, 180)
    )
    return df[valid].reset_index(drop=True)


def prepare_dalda_coordinates(dalda_df: pd.DataFrame, mapping: ColumnMapping) -> pd.DataFrame:
    df = dalda_df.copy()
    df["_match_lat"] = np.nan
    df["_match_lon"] = np.nan
    for idx, row in df.iterrows():
        lat, lon = _resolve_coords(row, mapping)
        if lat is not None and lon is not None:
            df.at[idx, "_match_lat"] = lat
            df.at[idx, "_match_lon"] = lon
    return df


@dataclass
class _CensusIndex:
    tree: Any
    coords_rad: np.ndarray
    indices: np.ndarray
    df: pd.DataFrame
    name_col: str
    columns: list[str]


def build_census_index(census_df: pd.DataFrame, name_col: str | None) -> _CensusIndex:
    census_df = prepare_census_coordinates(census_df)
    if census_df.empty:
        raise ValueError("No census rows with valid GPS coordinates.")

    name_col = name_col or detect_column(list(census_df.columns), NAME_HINTS) or "Name of Outlet"
    coords = census_df[["Latitude", "Longitude"]].to_numpy(dtype=float)
    coords_rad = np.radians(coords)
    indices = np.arange(len(census_df))

    if HAS_BALLTREE:
        tree = BallTree(coords_rad, metric="haversine")
    else:
        tree = None

    return _CensusIndex(
        tree=tree,
        coords_rad=coords_rad,
        indices=indices,
        df=census_df,
        name_col=name_col,
        columns=list(census_df.columns),
    )


def _query_candidates(
    index: _CensusIndex,
    lat: float,
    lon: float,
    max_radius_m: float,
    top_n: int,
) -> list[tuple[int, float]]:
    radius_rad = max_radius_m / EARTH_RADIUS_M
    point = np.radians([[lat, lon]])

    if index.tree is not None:
        dist_rad, ind = index.tree.query(point, k=min(top_n, len(index.df)))
        results = []
        for d, i in zip(dist_rad[0], ind[0]):
            if i < 0:
                continue
            dist_m = d * EARTH_RADIUS_M
            if dist_m <= max_radius_m:
                results.append((int(i), float(dist_m)))
        results.sort(key=lambda x: x[1])
        return results[:top_n]

    # Fallback: brute force (slower)
    distances = []
    for i, (clat, clon) in enumerate(index.df[["Latitude", "Longitude"]].to_numpy()):
        d = haversine_distance(lat, lon, float(clat), float(clon))
        if d <= max_radius_m:
            distances.append((i, d))
    distances.sort(key=lambda x: x[1])
    return distances[:top_n]


def _match_one_row(
    dalda_row: pd.Series,
    dalda_mapping: ColumnMapping,
    index: _CensusIndex,
    settings: MatchSettings,
    dalda_name_col: str | None,
) -> dict[str, Any]:
    lat = dalda_row.get("_match_lat")
    lon = dalda_row.get("_match_lon")
    dalda_name = dalda_row.get(dalda_name_col) if dalda_name_col else None

    meta: dict[str, Any] = {
        "match_status": "Unmatched",
        "match_score": np.nan,
        "match_confidence": "",
        "match_distance_meters": np.nan,
        "match_proximity_score": np.nan,
        "match_name_score": np.nan,
        "match_candidates_evaluated": 0,
        "match_unmatched_reason": "",
    }

    if pd.isna(lat) or pd.isna(lon):
        meta["match_unmatched_reason"] = "Invalid or missing GPS on Dalda row"
        return meta

    candidates = _query_candidates(
        index, float(lat), float(lon), settings.max_radius_m, settings.top_n_candidates
    )
    meta["match_candidates_evaluated"] = len(candidates)

    if not candidates:
        meta["match_unmatched_reason"] = "No census shop within search radius"
        return meta

    best_idx = None
    best_score = -1.0
    best_dist = np.nan
    best_prox = np.nan
    best_name = np.nan

    for census_i, dist_m in candidates:
        census_row = index.df.iloc[census_i]
        prox = calculate_proximity_score(dist_m, settings.proximity_weight)
        name = calculate_name_similarity(
            dalda_name,
            census_row.get(index.name_col),
            settings.name_weight,
        )
        total = prox + name
        if total > best_score:
            best_score = total
            best_idx = census_i
            best_dist = dist_m
            best_prox = prox
            best_name = name

    if best_idx is None:
        meta["match_unmatched_reason"] = "No valid match found"
        return meta

    score = round(best_score, 2)
    conf = confidence_level(score, settings)

    status = "Matched" if score >= settings.min_score_threshold else "Below Threshold"
    reason = (
        ""
        if status == "Matched"
        else f"Best score {score} below threshold {settings.min_score_threshold}"
    )
    meta.update(
        {
            "match_status": status,
            "match_score": score,
            "match_confidence": conf,
            "match_distance_meters": round(best_dist, 2),
            "match_proximity_score": round(best_prox, 2),
            "match_name_score": round(best_name, 2),
            "match_unmatched_reason": reason,
            "_best_census_idx": best_idx,
        }
    )
    return meta


class _MatchProgress:
    """Thread-safe progress counter (like Pepsi console updates, for the UI)."""

    def __init__(
        self,
        total: int,
        callback: Callable[[int, int], None] | None,
        cancel_check: Callable[[], bool] | None,
        report_every: int = 25,
    ):
        self.total = total
        self.callback = callback
        self.cancel_check = cancel_check
        self.report_every = max(1, report_every)
        self.done = 0
        self.lock = threading.Lock()
        self.started = time.time()
        self._last_report = 0

    def tick(self, count: int = 1) -> None:
        if self.cancel_check and self.cancel_check():
            raise InterruptedError("Matching cancelled")
        with self.lock:
            self.done += count
            if self.callback and self.done - self._last_report >= self.report_every:
                self._last_report = self.done
                self.callback(self.done, self.total)

    def finish(self) -> None:
        if self.callback:
            self.callback(self.total, self.total)


def _process_chunk(
    dalda_chunk: pd.DataFrame,
    dalda_mapping: ColumnMapping,
    census_mapping: ColumnMapping,
    index: _CensusIndex,
    settings: MatchSettings,
    dalda_name_col: str | None,
    progress: _MatchProgress | None = None,
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for _, dalda_row in dalda_chunk.iterrows():
        out: dict[str, Any] = {}
        for col in dalda_chunk.columns:
            if col.startswith("_match_"):
                continue
            out[dalda_output_key(col, dalda_mapping)] = dalda_row[col]

        meta = _match_one_row(dalda_row, dalda_mapping, index, settings, dalda_name_col)

        best_idx = meta.pop("_best_census_idx", None)
        for key, val in meta.items():
            out[key] = val

        for col in index.columns:
            out_key = census_output_key(col, census_mapping)
            if best_idx is not None:
                val = index.df.iloc[best_idx].get(col, "")
                out[out_key] = "" if pd.isna(val) else val
            else:
                out[out_key] = ""

        rows_out.append(out)
        if progress:
            progress.tick(1)
    return rows_out


def run_matching(
    dalda_df: pd.DataFrame,
    census_df: pd.DataFrame,
    dalda_mapping: ColumnMapping,
    census_mapping: ColumnMapping | None = None,
    settings: MatchSettings | None = None,
    progress_callback=None,
    cancel_check=None,
) -> tuple[pd.DataFrame, MatchStats]:
    """
    Match every Dalda row to best census candidate. Output row count == input row count.
    """
    settings = settings or MatchSettings()
    dalda_original_cols = list(dalda_df.columns)

    dalda_prepared = prepare_dalda_coordinates(dalda_df, dalda_mapping)
    dalda_name_col = dalda_mapping.shop_name or detect_column(dalda_original_cols, NAME_HINTS)

    census_mapping = census_mapping or suggest_column_mapping(
        list(census_df.columns), prefer_census_defaults=True
    )
    census_name_col = census_mapping.shop_name
    index = build_census_index(census_df, census_name_col)

    n = len(dalda_prepared)
    # Smaller chunks + per-outlet progress = UI updates every ~25 outlets (Pepsi-style)
    chunk_size = min(250, max(50, n // max(settings.worker_threads * 8, 1)))
    chunks = [
        dalda_prepared.iloc[i : i + chunk_size]
        for i in range(0, n, chunk_size)
    ]

    report_every = 25 if n > 500 else 10
    match_progress = _MatchProgress(n, progress_callback, cancel_check, report_every)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_rows: list[dict[str, Any]] = [None] * n  # type: ignore
    chunk_start_indices = []
    pos = 0
    for ch in chunks:
        chunk_start_indices.append(pos)
        pos += len(ch)

    with ThreadPoolExecutor(max_workers=settings.worker_threads) as executor:
        futures = {}
        for start, chunk in zip(chunk_start_indices, chunks):
            if cancel_check and cancel_check():
                raise InterruptedError("Matching cancelled")
            fut = executor.submit(
                _process_chunk,
                chunk,
                dalda_mapping,
                census_mapping,
                index,
                settings,
                dalda_name_col,
                match_progress,
            )
            futures[fut] = start

        for fut in as_completed(futures):
            if cancel_check and cancel_check():
                raise InterruptedError("Matching cancelled")
            start = futures[fut]
            chunk_rows = fut.result()
            for i, row in enumerate(chunk_rows):
                all_rows[start + i] = row

    match_progress.finish()

    result_df = pd.DataFrame(all_rows)

    # Reorder: dalda_shop_id, dalda_outlet_name, other dalda_* → match_* → census_shop_id, census_outlet_name, other census_*
    dalda_cols = [c for c in result_df.columns if c.startswith("dalda_")]
    census_cols = [c for c in result_df.columns if c.startswith("census_")]
    match_cols = [c for c in MATCH_COLS if c in result_df.columns]

    def _sort_dalda(cols: list[str]) -> list[str]:
        priority = [DALDA_SHOP_ID_COL, DALDA_OUTLET_NAME_COL]
        rest = sorted(c for c in cols if c not in priority)
        return [c for c in priority if c in cols] + rest

    def _sort_census(cols: list[str]) -> list[str]:
        priority = [CENSUS_SHOP_ID_COL, CENSUS_OUTLET_NAME_COL]
        rest = sorted(c for c in cols if c not in priority)
        return [c for c in priority if c in cols] + rest

    ordered = _sort_dalda(dalda_cols) + match_cols + _sort_census(census_cols)
    extra = [c for c in result_df.columns if c not in ordered]
    result_df = result_df[ordered + extra]

    stats = MatchStats(total_dalda=n)
    matched_mask = result_df["match_status"] == "Matched"
    below_mask = result_df["match_status"] == "Below Threshold"
    stats.matched = int(matched_mask.sum())
    stats.below_threshold = int(below_mask.sum())
    stats.unmatched = int((result_df["match_status"] == "Unmatched").sum())
    if stats.matched:
        sub = result_df[matched_mask]
        stats.average_score = float(sub["match_score"].mean())
        stats.average_distance_m = float(sub["match_distance_meters"].mean())
        stats.high_confidence = int((sub["match_confidence"] == "High").sum())
        stats.medium_confidence = int((sub["match_confidence"] == "Medium").sum())
        stats.low_confidence = int((sub["match_confidence"] == "Low").sum())

    assert len(result_df) == n, f"Row count mismatch: {len(result_df)} != {n}"
    return result_df, stats
