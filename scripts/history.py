"""
SQLite store for the gas price history.

Only price *changes* are stored: a row is written to `price_changes` when a station's price for a fuel differs from the last stored
value. A NULL price records that the station stopped offering that fuel. The price at any time T is therefore the latest change at or
before T.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

GAS_TYPES: tuple[str, ...] = ("Régulier", "Super", "Diesel")
DEFAULT_DB_PATH: Path = Path(__file__).parent.parent / "data" / "history.sqlite"
KEEP_DAYS: int = 10  # The charts need 3-7 days; the rest is slack for re-clustering.
KEEP_BACKUPS: int = 7
SCHEMA_VERSION: int = 2

# Added in schema version 2; also applied to databases created at version 1.
_CLUSTERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    is_island INTEGER NOT NULL
);
"""

_SCHEMA = """
CREATE TABLE runs (
    run_id     INTEGER PRIMARY KEY,
    fetched_at TEXT NOT NULL
);
CREATE TABLE stations (
    id         INTEGER PRIMARY KEY,
    key        TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    brand      TEXT,
    address    TEXT,
    region     TEXT,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    cluster    INTEGER,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX idx_stations_coords ON stations (lon, lat);
CREATE TABLE price_changes (
    station_id  INTEGER NOT NULL REFERENCES stations (id) ON DELETE CASCADE,
    gas_type    TEXT NOT NULL,
    price       REAL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (station_id, gas_type, observed_at)
);
"""


@dataclass
class RunSummary:
    """Counts describing what a recorded run changed."""

    stations_seen: int
    new_stations: int
    renamed_stations: int
    price_changes: int


def _timestamp(moment: datetime) -> str:
    """
    Formats a moment as a sortable UTC timestamp string.

    Parameters
    ----------
    moment : datetime
        A timezone-aware datetime.

    Returns
    -------
    str
        Timestamp such as ``2026-11-15T14:30:00Z``.
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_name(name: str) -> str:
    """
    Collapses runs of whitespace (the feed has stray carriage returns and newlines) in a station name.

    Parameters
    ----------
    name : str
        Raw station name.

    Returns
    -------
    str
        Single-spaced, stripped name.
    """
    return re.sub(r"\s+", " ", name).strip()


def station_key(name: str, lon: float, lat: float) -> str:
    """
    Builds the repeatable station key, since the feed has no stable identifier.

    Parameters
    ----------
    name : str
        Station name. Runs of whitespace (including ``\\r\\n``) are collapsed.
    lon : float
        Longitude in degrees.
    lat : float
        Latitude in degrees.

    Returns
    -------
    str
        Key of the form ``name|lon|lat`` with coordinates at 5 decimals.
    """
    return f"{_clean_name(name)}|{lon:.5f}|{lat:.5f}"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """
    Opens the history database, creating the file and schema if needed.

    Parameters
    ----------
    path : Path or str, optional
        Database file. Defaults to the ``ESSENCE_DB`` environment variable, then ``data/history.sqlite``.

    Returns
    -------
    sqlite3.Connection
        Connection in WAL mode with foreign keys enabled.

    Raises
    ------
    RuntimeError
        If the database was created by a newer version of this module.
    """
    db_path = Path(path or os.environ.get("ESSENCE_DB") or DEFAULT_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # --- Create or validate the schema -------------------------------------------------
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        with conn:
            conn.executescript(_SCHEMA + _CLUSTERS_SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    elif version < SCHEMA_VERSION:
        # Version 1 -> 2 only adds the clusters table, so existing data is untouched.
        with conn:
            conn.executescript(_CLUSTERS_SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    elif version > SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{db_path} has schema version {version}; this code supports up to {SCHEMA_VERSION}")
    return conn


def _clean(value: object) -> float | None:
    """
    Converts a price cell to a float, mapping NaN and missing values to None.

    Parameters
    ----------
    value : object
        A cell from a price column.

    Returns
    -------
    float or None
        The price, or None if it is missing.
    """
    return None if pd.isna(value) else float(value)


def record_run(conn: sqlite3.Connection, stations: gpd.GeoDataFrame, fetched_at: datetime | None = None) -> RunSummary:
    """
    Records a fetch: upserts stations and stores the price changes since the last run.

    The whole run is written in one transaction, so a failure leaves the database untouched.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `connect`.
    stations : geopandas.GeoDataFrame
        Parsed and region-filtered stations (columns Name, brand, Address, Region, geometry and one column per gas type).
    fetched_at : datetime, optional
        Time of the fetch. Defaults to now.

    Returns
    -------
    RunSummary
        Counts of what the run added.
    """
    now = _timestamp(fetched_at or datetime.now(timezone.utc))
    new = renamed = changes = 0

    with conn:
        conn.execute("INSERT INTO runs (fetched_at) VALUES (?)", (now,))

        # --- Load existing state -------------------------------------------------------
        by_key: dict[str, int] = {key: sid for sid, key in conn.execute("SELECT id, key FROM stations")}
        by_coords: dict[tuple[str, str], list[int]] = {}
        for sid, lon, lat in conn.execute("SELECT id, lon, lat FROM stations"):
            by_coords.setdefault((f"{lon:.5f}", f"{lat:.5f}"), []).append(sid)

        # Latest stored price per (station, fuel); the max() picks the most recent row of each group.
        last: dict[tuple[int, str], float | None] = {
            (sid, gas): price
            for sid, gas, price, _ in conn.execute(
                "SELECT station_id, gas_type, price, MAX(observed_at) FROM price_changes GROUP BY station_id, gas_type"
            )
        }

        # --- Upsert stations and diff prices -------------------------------------------
        seen: set[int] = set()
        for row in stations.itertuples(index=False):
            lon, lat = row.geometry.x, row.geometry.y
            key = station_key(row.Name, lon, lat)
            sid = by_key.get(key)

            if sid is None:
                # A renamed station keeps its history if exactly one known station sits at the same coordinates.
                candidates = [c for c in by_coords.get((f"{lon:.5f}", f"{lat:.5f}"), []) if c not in seen]
                if len(candidates) == 1:
                    sid = candidates[0]
                    conn.execute("UPDATE stations SET key=?, name=? WHERE id=?", (key, _clean_name(row.Name), sid))
                    by_key[key] = sid
                    renamed += 1
                else:
                    cur = conn.execute(
                        "INSERT INTO stations (key, name, brand, address, region, lat, lon, first_seen, last_seen) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, _clean_name(row.Name), row.brand, row.Address, row.Region, lat, lon, now, now),
                    )
                    sid = cur.lastrowid
                    by_key[key] = sid
                    by_coords.setdefault((f"{lon:.5f}", f"{lat:.5f}"), []).append(sid)
                    new += 1

            # The feed should not repeat a station, but the first occurrence wins if it does.
            if sid in seen:
                continue
            seen.add(sid)
            conn.execute(
                "UPDATE stations SET brand=?, address=?, region=?, last_seen=? WHERE id=?",
                (row.brand, row.Address, row.Region, now, sid),
            )

            for gas in GAS_TYPES:
                price = _clean(getattr(row, gas, None))
                if price != last.get((sid, gas)):
                    conn.execute(
                        "INSERT INTO price_changes (station_id, gas_type, price, observed_at) VALUES (?, ?, ?, ?)",
                        (sid, gas, price, now),
                    )
                    changes += 1

    return RunSummary(stations_seen=len(seen), new_stations=new, renamed_stations=renamed, price_changes=changes)


def save_clusters(conn: sqlite3.Connection, labels: dict[str, int], names: dict[int, str], islands: set[int]) -> int:
    """
    Freezes a clustering: replaces the stored clusters and the cluster of every station.

    Stations that are absent from `labels` are left unassigned (NULL) so `freeze_clusters.assign_new_stations` can place them. A label
    of -1 records that the station was deliberately left unclustered.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `connect`.
    labels : dict[str, int]
        Cluster identifier of each station, keyed by `station_key`. Unclustered stations are -1.
    names : dict[int, str]
        Display name of each cluster identifier (at least every non-negative label).
    islands : set[int]
        Identifiers of the clusters that lie on the Montréal island.

    Returns
    -------
    int
        Number of stations whose cluster was set.
    """
    with conn:
        conn.execute("DELETE FROM clusters")
        conn.execute("UPDATE stations SET cluster = NULL")
        conn.executemany(
            "INSERT INTO clusters (id, name, is_island) VALUES (?, ?, ?)",
            [(cid, name, int(cid in islands)) for cid, name in names.items()],
        )
        updated = conn.executemany("UPDATE stations SET cluster = ? WHERE key = ?", [(cid, key) for key, cid in labels.items()])
    return updated.rowcount


def epoch_seconds(stamps: pd.Series) -> np.ndarray:
    """
    Converts stored UTC timestamp strings to epoch seconds.

    Parameters
    ----------
    stamps : pandas.Series
        Timestamps such as ``2026-11-15T14:30:00Z``.

    Returns
    -------
    numpy.ndarray
        Seconds since the Unix epoch, as floats.
    """
    parsed = pd.to_datetime(stamps, utc=True)
    return ((parsed - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy()


def hourly_prices(conn: sqlite3.Connection, gas_type: str, grid: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Rebuilds every station's price at each time on a grid from the stored changes.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `history.connect`.
    gas_type : str
        Fuel to rebuild.
    grid : numpy.ndarray
        Epoch seconds, ascending, at which to sample the prices.

    Returns
    -------
    stations : pandas.DataFrame
        Stations still in the feed (columns id, name, brand, address, region, lat, lon, cluster), in the row order of the matrix.
    prices : numpy.ndarray
        Array of shape (stations, grid) with NaN where a station had no known price (not yet seen, or no longer sold).
    """
    # --- Load the stations that are still in the latest run ----------------------------
    stations = pd.read_sql_query(
        "SELECT id, name, brand, address, region, lat, lon, cluster FROM stations "
        "WHERE last_seen = (SELECT MAX(fetched_at) FROM runs) ORDER BY id",
        conn,
    )
    changes = pd.read_sql_query(
        "SELECT station_id, price, observed_at FROM price_changes WHERE gas_type = ? ORDER BY station_id, observed_at",
        conn,
        params=(gas_type,),
    )
    changes["t"] = epoch_seconds(changes["observed_at"])
    by_station = {sid: g for sid, g in changes.groupby("station_id")}

    # --- Sample each station's step function on the grid -------------------------------
    prices = np.full((len(stations), len(grid)), np.nan)
    for row, sid in enumerate(stations["id"]):
        g = by_station.get(sid)
        if g is None:
            continue
        # The price at T is the last change at or before T; earlier than the first change, the price is unknown.
        idx = np.searchsorted(g["t"].to_numpy(), grid, side="right") - 1
        values = g["price"].to_numpy(dtype=float)
        prices[row] = np.where(idx >= 0, values[np.maximum(idx, 0)], np.nan)
    return stations, prices


def fit_grid(conn: sqlite3.Connection, days: int) -> np.ndarray | None:
    """
    Builds the hourly sampling grid for the most recent `days` days of history.

    The grid ends at the latest run and starts `days` days earlier, or at the first run if there is less history than that.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `connect`.
    days : int
        Maximum window length in days.

    Returns
    -------
    numpy.ndarray or None
        Epoch seconds, ascending, one per hour. None if no run has been recorded.
    """
    first, latest = conn.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM runs").fetchone()
    if latest is None:
        return None
    end = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    start = max(datetime.strptime(first, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp(), end - days * 86400)
    hours = int((end - start) // 3600)
    return end - 3600.0 * np.arange(hours, -1, -1)


def span_hours(conn: sqlite3.Connection) -> float:
    """
    Measures how much history the database holds.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `connect`.

    Returns
    -------
    float
        Hours between the first and the latest recorded run; 0 if no run has been recorded.
    """
    grid = fit_grid(conn, KEEP_DAYS)
    return 0.0 if grid is None else float(grid[-1] - grid[0]) / 3600


def prune(conn: sqlite3.Connection, keep_days: int = KEEP_DAYS, now: datetime | None = None) -> None:
    """
    Deletes history older than the retention window.

    For every station and fuel, the last change at or before the cutoff is kept so the price at the start of the window stays known.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `connect`.
    keep_days : int, default=10
        Retention window in days.
    now : datetime, optional
        Reference time. Defaults to the current time.
    """
    cutoff = _timestamp((now or datetime.now(timezone.utc)) - timedelta(days=keep_days))
    with conn:
        conn.execute(
            "DELETE FROM price_changes WHERE observed_at < :cutoff AND observed_at < ("
            "  SELECT MAX(p.observed_at) FROM price_changes p"
            "  WHERE p.station_id = price_changes.station_id AND p.gas_type = price_changes.gas_type AND p.observed_at <= :cutoff)",
            {"cutoff": cutoff},
        )
        conn.execute("DELETE FROM runs WHERE fetched_at < ?", (cutoff,))
        # Stations that left the feed; their changes go with them via ON DELETE CASCADE.
        conn.execute("DELETE FROM stations WHERE last_seen < ?", (cutoff,))


def backup(
    conn: sqlite3.Connection,
    dest_dir: Path | str | None = None,
    keep: int = KEEP_BACKUPS,
    now: datetime | None = None,
) -> Path | None:
    """
    Writes a daily backup of the database, at most once per UTC day.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `connect`.
    dest_dir : Path or str, optional
        Directory for backup files. Defaults to a ``backups`` folder beside the database file.
    keep : int, default=7
        Number of most recent backups to retain.
    now : datetime, optional
        Reference time. Defaults to the current time.

    Returns
    -------
    Path or None
        The new backup file, or None if today's backup already exists.
    """
    # Keeping backups beside the database means a test or alternate ESSENCE_DB never writes into the real data folder.
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    dest = Path(dest_dir) if dest_dir else db_file.parent / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"history-{(now or datetime.now(timezone.utc)).astimezone(timezone.utc):%Y-%m-%d}.sqlite"
    if target.exists():
        return None

    # Write to a temporary name first so a crash never leaves a truncated file that looks like a good backup.
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    dst = sqlite3.connect(tmp)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    tmp.replace(target)

    for old in sorted(dest.glob("history-*.sqlite"))[:-keep]:
        old.unlink()
    return target
