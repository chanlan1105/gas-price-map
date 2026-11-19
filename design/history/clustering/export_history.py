"""
Exports the price history database to CSV files, so the analysis can be rerun without the (git-ignored) database.

Usage::

    uv run python design/history/clustering/export_history.py [path/to/history.sqlite]

The database is opened read-only. Only the standard library is used. The CSV files are written to ``data/`` next to this script.
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

HERE: Path = Path(__file__).parent
DEFAULT_DB: Path = HERE.parents[2] / "data" / "history.sqlite"
OUT_DIR: Path = HERE / "data"

# Table name -> query. Rows are ordered so repeated exports of the same data give identical files.
QUERIES: dict[str, str] = {
    "stations": "SELECT id, name, brand, address, region, lat, lon, first_seen, last_seen FROM stations ORDER BY id",
    "runs": "SELECT run_id, fetched_at FROM runs ORDER BY fetched_at",
    "price_changes": "SELECT station_id, gas_type, price, observed_at FROM price_changes ORDER BY observed_at, station_id, gas_type",
}


def export_tables(db_path: Path, out_dir: Path) -> dict[str, int]:
    """
    Writes each table in `QUERIES` to a CSV file.

    Parameters
    ----------
    db_path : pathlib.Path
        History database to read.
    out_dir : pathlib.Path
        Directory for the CSV files; created if missing.

    Returns
    -------
    dict[str, int]
        Number of data rows written, per table.

    Raises
    ------
    FileNotFoundError
        If `db_path` does not exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"No database at {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    # mode=ro guarantees the analysis can never modify the database.
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        for name, query in QUERIES.items():
            cursor = conn.execute(query)
            with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow([col[0] for col in cursor.description])
                rows = cursor.fetchall()
                writer.writerows(rows)
            counts[name] = len(rows)
    finally:
        conn.close()
    return counts


def main() -> None:
    """
    Exports the database given on the command line (or the default one) and prints a summary.
    """
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    for name, count in export_tables(db_path, OUT_DIR).items():
        print(f"{name}: {count} rows")


if __name__ == "__main__":
    main()
