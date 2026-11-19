"""
Tests whether the choice of snapshot time matters: fits a snapshot clustering at many different times and scores each one.

Usage (from the repository root, after ``export_history.py``)::

    uv run python design/history/clustering/snapshot_timing.py

For every `STRIDE`-th run, the clusters are fitted on the premium at that single run (today's method: ``snapshot``, weight 1.5) and
scored on the whole window. One run out of about 190 is in the scored data, so the overlap is negligible. The spread of the scores shows
how much a lucky or unlucky snapshot could matter. Each snapshot is also described by how spread out the stations' prices were at that
time, to check whether quiet moments (stations close in price) give worse clusters.

Writes ``output/snapshot_timing.csv`` and ``output/snapshot_timing_report.md``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE: Path = Path(__file__).parent
sys.path.insert(0, str(HERE))  # For analysis.py and ward_experiment.py.
sys.path.insert(0, str(HERE.parents[2]))  # For scripts.clustering.

from analysis import GAS_TYPE, load, premium_matrix, price_matrix  # noqa: E402
from scripts.clustering import Params  # noqa: E402
from ward_experiment import TARGET_CLUSTERS, build_features, cluster_to_target, score  # noqa: E402

OUT_DIR: Path = HERE / "output"
STRIDE: int = 6  # One snapshot every 3 hours.
SNAPSHOT_WEIGHT: float = 1.5  # `Params.alpha`, the weight in use today.


def main() -> None:
    """
    Fits and scores a snapshot clustering at each sampled run, then writes the results.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    stations, runs, changes = load()
    prices = price_matrix(stations, runs, changes, GAS_TYPE)
    stations = stations.loc[prices.index].reset_index()
    xy = stations[["x_km", "y_km"]].to_numpy()
    p = Params()
    neighbours = cKDTree(xy).query(xy, k=p.smooth_k)[1]
    premium = premium_matrix(prices)

    rows = []
    for t in range(0, prices.shape[1], STRIDE):
        features = build_features("snapshot", SNAPSHOT_WEIGHT, premium.iloc[:, : t + 1], xy, neighbours, p.clip)
        labels = cluster_to_target(stations, features, p, TARGET_CLUSTERS)
        snapshot = np.clip(premium.iloc[:, t].to_numpy(), -p.clip, p.clip)
        rows.append({"run": t, "local_time": premium.columns[t], "premium_std": snapshot.std(),
                     "premium_iqr": np.subtract(*np.percentile(snapshot, [75, 25])),
                     **score(labels, premium, xy)})
        print(f"run {t:3d}  {premium.columns[t]:%a %H:%M}  shape R² {rows[-1]['shape_r2']:.3f}", flush=True)
    results = pd.DataFrame(rows)

    # --- References on the same scale -------------------------------------------------
    geography = score(cluster_to_target(stations, xy, p, TARGET_CLUSTERS), premium, xy)
    features = build_features("trajectory", 3.0, premium, xy, neighbours, p.clip)
    trajectory = score(cluster_to_target(stations, features, p, TARGET_CLUSTERS), premium, xy)

    results.to_csv(OUT_DIR / "snapshot_timing.csv", index=False)
    shape, level = results.shape_r2, results.level_r2
    corr_std = results.premium_std.corr(results.shape_r2)
    corr_iqr = results.premium_iqr.corr(results.shape_r2)
    best, worst = results.loc[shape.idxmax()], results.loc[shape.idxmin()]
    lines = [
        "# Snapshot timing experiment\n",
        f"{len(results)} snapshots, one every {STRIDE // 2} hours, each fitted alone (weight {SNAPSHOT_WEIGHT}, about {TARGET_CLUSTERS} clusters) "
        "and scored on the whole window.\n",
        "| | Shape R² | Level R² | Corr |", "|---|---|---|---|",
        f"| Snapshot, worst | {shape.min():.3f} | {level.min():.3f} | {results['corr'].min():.2f} |",
        f"| Snapshot, median | {shape.median():.3f} | {level.median():.3f} | {results['corr'].median():.2f} |",
        f"| Snapshot, best | {shape.max():.3f} | {level.max():.3f} | {results['corr'].max():.2f} |",
        f"| Geography only | {geography['shape_r2']:.3f} | {geography['level_r2']:.3f} | {geography['corr']:.2f} |",
        f"| Trajectory (weight 3, fitted on the whole window: in-sample) | {trajectory['shape_r2']:.3f} | {trajectory['level_r2']:.3f} "
        f"| {trajectory['corr']:.2f} |\n",
        f"Snapshots that beat geography on shape R²: {(shape > geography['shape_r2']).sum()} of {len(results)}. "
        f"Snapshots within 0.01 of the trajectory on shape R²: {(shape > trajectory['shape_r2'] - 0.01).sum()} of {len(results)}.\n",
        f"Best snapshot: {best.local_time:%a %H:%M} (price spread std {best.premium_std:.1f}¢). "
        f"Worst: {worst.local_time:%a %H:%M} (std {worst.premium_std:.1f}¢).",
        f"Correlation between the spread of prices at the snapshot and its shape R²: {corr_std:.2f} (std), {corr_iqr:.2f} (IQR).\n",
        "Shape R² by time of day (mean over days):\n",
        "| Hour of day | Snapshots | Shape R² |", "|---|---|---|",
    ]
    by_hour = results.assign(hour=results.local_time.dt.hour // 6 * 6).groupby("hour").shape_r2.agg(["count", "mean"])
    lines += [f"| {h:02d}:00-{h + 5:02d}:59 | {int(r['count'])} | {r['mean']:.3f} |" for h, r in by_hour.iterrows()]
    (OUT_DIR / "snapshot_timing_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
