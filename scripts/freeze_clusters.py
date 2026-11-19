"""
Freezes the station clusters used as regions on the statistics page.

Run once with ``uv run python -m scripts.freeze_clusters``. The clustering is fitted on the hourly Régulier price history of the
last `FIT_DAYS` days (or all of it, if shorter) and stored in the history database, so the regions stay stable while prices move.
The fit reads only the database, so it needs no network and can be reproduced from a backup. Stations that appear later are placed
in the nearest frozen cluster by `assign_new_stations`.
"""
from __future__ import annotations

import argparse
import sqlite3

import numpy as np
from scipy.spatial import cKDTree

from scripts import history
from scripts.clustering import LAT0, Params, fit_target, island_clusters, label_clusters, load_history_fit, quality_lines, report

TARGET_CLUSTERS: int = 19  # Matches the cluster preview's default.
FIT_GAS_TYPE: str = "Régulier"  # The only fuel in scope.
FIT_DAYS: int = 3  # The fit uses the most recent days of history, or all there is if less.
MIN_FIT_HOURS: int = 24  # Less history than this cannot show the daily cycle, so freezing is refused.


def _project(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """
    Projects coordinates into the kilometre grid used by the clustering.

    Parameters
    ----------
    lon : numpy.ndarray
        Longitudes in degrees.
    lat : numpy.ndarray
        Latitudes in degrees.

    Returns
    -------
    numpy.ndarray
        Array of shape (n, 2) with the x and y positions in kilometres.
    """
    x = (lon + 73.6) * 111.32 * np.cos(np.radians(LAT0))
    y = (lat - LAT0) * 110.57
    return np.c_[x, y]


def has_frozen_clusters(conn: sqlite3.Connection) -> bool:
    """
    Checks whether clusters have been frozen.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `history.connect`.

    Returns
    -------
    bool
        True if the clusters table has any rows.
    """
    return conn.execute("SELECT EXISTS (SELECT 1 FROM clusters)").fetchone()[0] == 1


def assign_new_stations(conn: sqlite3.Connection, max_edge_km: float | None = None) -> int:
    """
    Assigns stations with no cluster yet to the cluster of their nearest clustered station.

    Stations farther than `max_edge_km` from every clustered station are recorded as unclustered (-1), like the rural stations at
    freeze time. Does nothing when no clusters are frozen.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `history.connect`.
    max_edge_km : float, optional
        Largest distance to a clustered station that still joins its cluster. Defaults to `Params.max_edge_km`.

    Returns
    -------
    int
        Number of stations that were assigned.
    """
    if not has_frozen_clusters(conn):
        return 0
    limit = Params().max_edge_km if max_edge_km is None else max_edge_km

    # --- Load the placed and unplaced stations -----------------------------------------
    placed = conn.execute("SELECT lon, lat, cluster FROM stations WHERE cluster >= 0").fetchall()
    pending = conn.execute("SELECT id, lon, lat FROM stations WHERE cluster IS NULL").fetchall()
    if not pending or not placed:
        return 0
    placed_xy = _project(np.array([r[0] for r in placed]), np.array([r[1] for r in placed]))
    placed_cluster = np.array([r[2] for r in placed])
    pending_xy = _project(np.array([r[1] for r in pending]), np.array([r[2] for r in pending]))

    # --- Join the nearest cluster if it is close enough --------------------------------
    dist, nearest = cKDTree(placed_xy).query(pending_xy)
    updates = [(int(placed_cluster[j]) if d <= limit else -1, row[0]) for row, d, j in zip(pending, dist, nearest)]
    with conn:
        conn.executemany("UPDATE stations SET cluster = ? WHERE id = ?", updates)
    return len(updates)


def freeze(conn: sqlite3.Connection, force: bool = False) -> int:
    """
    Fits clusters on the stored price history and stores them.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `history.connect`.
    force : bool, default=False
        Replace clusters that are already frozen.

    Returns
    -------
    int
        Number of clusters stored.

    Raises
    ------
    RuntimeError
        If clusters are already frozen and `force` is False, or if the database holds less than `MIN_FIT_HOURS` of history.
    """
    if has_frozen_clusters(conn) and not force:
        raise RuntimeError("Clusters are already frozen; pass --force to refit them (the regions will change).")
    available = history.span_hours(conn)
    if available < MIN_FIT_HOURS:
        raise RuntimeError(f"Only {available:.0f} h of history; at least {MIN_FIT_HOURS} h are needed to fit clusters.")

    # --- Fit on the stored history -----------------------------------------------------
    stations, premium = load_history_fit(conn, FIT_DAYS, FIT_GAS_TYPE)
    params = Params()
    clustered, count, threshold = fit_target(stations, FIT_GAS_TYPE, params, TARGET_CLUSTERS, premium)
    print(f"Fitted {count} clusters (Ward threshold {threshold:.1f})")
    print("\n".join(quality_lines(clustered, FIT_GAS_TYPE, params, TARGET_CLUSTERS, premium)))

    # --- Store the clusters, then place the stations the fit did not cover -------------
    # Stations without enough priced hours are left out of the labels (NULL), so they are placed by proximity like new stations.
    fitted = clustered[clustered.fitted]
    labels = {row.key: int(row.cluster) for row in fitted.itertuples(index=False)}
    names = label_clusters(clustered)
    saved = history.save_clusters(conn, labels, names, set(island_clusters(clustered)))
    extra = assign_new_stations(conn)
    print(f"Stored {len(names)} clusters for {saved} stations; assigned {extra} more by proximity")
    print(report(clustered, FIT_GAS_TYPE, premium).assign(name=lambda r: r.index.map(names)).to_string())
    return len(names)


def main() -> None:
    """
    Runs the freeze command.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="refit even if clusters are already frozen")
    args = ap.parse_args()

    conn = history.connect()
    try:
        freeze(conn, args.force)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
