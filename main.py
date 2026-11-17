"""
Entry point for the automated build: fetches the station feed once, records price history, and renders the three maps.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from scripts import freeze_clusters, history, stats
from scripts.interactive_map import REGIONS, MapData, MapRenderer

# Maps each gas type to the page it is rendered on.
MAP_FILES: dict[str, str] = {"Régulier": "index.html", "Super": "super.html", "Diesel": "diesel.html"}


def record_history(map_data: MapData, fetched_at: datetime) -> None:
    """
    Records the filtered stations in the history database, then prunes old data and takes the daily backup.

    Parameters
    ----------
    map_data : MapData
        Fetched, parsed and region-filtered station data.
    fetched_at : datetime
        Time the feed was fetched.
    """
    conn = history.connect()
    try:
        summary = history.record_run(conn, map_data.df, fetched_at)
        placed = freeze_clusters.assign_new_stations(conn)
        if placed:
            print(f"History: placed {placed} new stations in frozen clusters")
        print(
            f"History: {summary.stations_seen} stations, {summary.new_stations} new, "
            f"{summary.renamed_stations} renamed, {summary.price_changes} price changes"
        )
        history.prune(conn)
        backup_path = history.backup(conn)
        if backup_path is not None:
            print(f"History backup written to {backup_path}")
    finally:
        conn.close()


def render_statistics() -> None:
    """
    Builds ``stats.html`` from the history database, which is only read.
    """
    conn = history.connect()
    try:
        data = stats.build_stats(conn)
    finally:
        conn.close()
    if data is None:
        print("Statistics page skipped: no history recorded yet")
        return
    print(f"Statistics page saved to {stats.render_stats_page(data)}")


def main() -> int:
    """
    Runs the full build.

    Returns
    -------
    int
        Process exit code: 1 if recording the history failed (the maps are still rendered), otherwise 0.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-history", action="store_true", help="render the maps without touching the history database")
    args = ap.parse_args()

    # --- Fetch and parse the feed (once) -----------------------------------------------
    map_data = MapData()
    map_data.fetch_data()
    fetched_at = datetime.now(timezone.utc)
    map_data.parse_data()
    map_data.filter_regions(REGIONS)

    # --- Record history ----------------------------------------------------------------
    # A history failure must never block the deploy, so it is reported and reflected in the exit code only.
    exit_code = 0
    if not args.no_history:
        try:
            record_history(map_data, fetched_at)
        except Exception as exc:  # noqa: BLE001 - any failure here (sqlite, disk, pandas) must not stop the maps
            print(f"History recording failed: {exc!r}", file=sys.stderr)
            exit_code = 1

    # --- Render the maps ---------------------------------------------------------------
    for gas_type, filename in MAP_FILES.items():
        print(f"Rendering {gas_type} map...")
        MapRenderer(map_data.df, gas_type=gas_type, filename=filename).render()

    # --- Render the statistics page ----------------------------------------------------
    # Also runs with --no-history (it only reads the database), but a failure must not stop the deploy.
    try:
        render_statistics()
    except Exception as exc:  # noqa: BLE001 - sqlite, disk or pandas failures must not stop the maps
        print(f"Statistics page failed: {exc!r}", file=sys.stderr)
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
