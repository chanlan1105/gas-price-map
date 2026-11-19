"""
Builds the statistics page: hourly price series per frozen cluster, plus the current stations for the minimap.

The page is a static file, so everything it needs is embedded in ``build/stats.html``. The browser combines the per-cluster series into
the "All regions" and "rest of the island" views, which keeps this export small.
"""
from __future__ import annotations

import json
import sqlite3
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.history import hourly_prices
from scripts.interactive_map import COLORS, build_colormap

STATS_GAS_TYPE: str = "Régulier"
HISTORY_DAYS: int = 7  # The longest window on the page.
UNCLUSTERED: int = -1  # Series id for stations that belong to no cluster.
TEMPLATE_PATH: Path = Path(__file__).parent.parent / "assets" / "stats.html"
DATA_PLACEHOLDER: str = "__STATS_DATA__"


def _json_list(values: np.ndarray, digits: int = 2) -> list[float | None]:
    """
    Converts an array to a JSON-safe list, mapping NaN to None.

    Parameters
    ----------
    values : numpy.ndarray
        One-dimensional array of floats.
    digits : int, default=2
        Decimal places to keep.

    Returns
    -------
    list[float or None]
        Rounded values with None in place of NaN.
    """
    return [None if np.isnan(v) else round(float(v), digits) for v in values]


def _series(block: np.ndarray) -> dict[str, list[float | None]]:
    """
    Summarizes a block of station prices at every time step.

    Parameters
    ----------
    block : numpy.ndarray
        Array of shape (stations, times) with NaN for missing prices.

    Returns
    -------
    dict[str, list[float or None]]
        Station count ``n``, the ``sum`` of prices (so means can be recombined), ``min`` and ``max`` per time step. Steps with no
        prices have ``n`` = 0 and None elsewhere.
    """
    with warnings.catch_warnings():
        # An all-NaN column is expected (nothing sold yet) and maps to None.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        low = np.nanmin(block, axis=0) if block.shape[0] else np.full(block.shape[1], np.nan)
        high = np.nanmax(block, axis=0) if block.shape[0] else np.full(block.shape[1], np.nan)
    count = (~np.isnan(block)).sum(axis=0)
    return {
        "n": [int(c) for c in count],
        "sum": _json_list(np.where(count > 0, np.nansum(block, axis=0), np.nan)),
        "min": _json_list(low, 1),
        "max": _json_list(high, 1),
    }


def build_stats(conn: sqlite3.Connection, gas_type: str = STATS_GAS_TYPE, days: int = HISTORY_DAYS) -> dict | None:
    """
    Builds the data embedded in the statistics page.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `history.connect`.
    gas_type : str, default="Régulier"
        Fuel to report.
    days : int, default=7
        Length of the history, ending at the latest recorded run.

    Returns
    -------
    dict or None
        The page data, or None if no run has been recorded yet. Keys: ``gas_type``, ``times`` (hourly epoch seconds), ``clusters``
        (id, name, island flag, station count and series, with id -1 for unclustered stations), ``stations`` (rows of lat, lon, price,
        cluster, name and colour for the minimap) and ``colors`` (the colour scale breakpoints for the legend).
    """
    latest = conn.execute("SELECT MAX(fetched_at) FROM runs").fetchone()[0]
    if latest is None:
        return None

    # --- Sample the prices hourly, ending at the latest run ----------------------------
    end = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    grid = np.array([(end - timedelta(hours=h)).timestamp() for h in range(days * 24, -1, -1)])
    stations, prices = hourly_prices(conn, gas_type, grid)
    ids = stations["cluster"].fillna(UNCLUSTERED).astype(int).to_numpy()

    # --- Summarize each frozen cluster, then the stations outside every cluster --------
    info = conn.execute("SELECT id, name, is_island FROM clusters ORDER BY is_island DESC, name").fetchall()
    clusters = [
        {"id": cid, "name": name, "island": bool(island), "stations": int((ids == cid).sum()), "series": _series(prices[ids == cid])}
        for cid, name, island in info
    ]
    if (ids < 0).any():
        clusters.append(
            {"id": UNCLUSTERED, "name": "Other stations", "island": False, "stations": int((ids < 0).sum()),
             "series": _series(prices[ids < 0])}
        )

    # --- Colour the current stations with the main map's scale -------------------------
    current = pd.Series(prices[:, -1])
    colormap = build_colormap(current)
    rows = [
        [round(lat, 5), round(lon, 5), round(float(p), 1), int(cid), name, colormap(p)[:7]]
        for lat, lon, p, cid, name in zip(stations["lat"], stations["lon"], current, ids, stations["name"])
        if not np.isnan(p)
    ]
    return {
        "gas_type": gas_type,
        "times": [int(t) for t in grid],
        "clusters": clusters,
        "stations": rows,
        "colors": {"index": [round(float(v), 2) for v in colormap.index], "colors": COLORS},
    }


def render_stats_page(data: dict, output_dir: Path = Path("build")) -> Path:
    """
    Writes the statistics page with its data embedded.

    Parameters
    ----------
    data : dict
        Output of `build_stats`.
    output_dir : Path, default=Path("build")
        Directory to write ``stats.html`` into.

    Returns
    -------
    Path
        Path of the written page.
    """
    # "</" is escaped so a station name can never close the script tag that holds the data.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE_PATH.read_text(encoding="utf-8").replace(DATA_PLACEHOLDER, payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "stats.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path
