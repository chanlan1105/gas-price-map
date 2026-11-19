"""
Compares ways of building the clustering features: today's single price snapshot against features built from the price history.

Usage (from the repository root, after ``export_history.py``)::

    uv run python design/history/clustering/ward_experiment.py

The experiment uses the project's own clustering code (graph, Ward linkage, small-cluster merge, size cap from ``scripts/clustering.py``)
and only swaps the feature matrix. To test whether a clustering generalizes, the history is split in two halves: clusters are fitted on one
half and scored on the other half, in both directions. A good clustering of stations that "move together" should still group them
together in prices it never saw.

Writes ``output/ward_results.csv`` and ``output/ward_report.md``.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score

HERE: Path = Path(__file__).parent
sys.path.insert(0, str(HERE))  # For analysis.py.
sys.path.insert(0, str(HERE.parents[2]))  # For scripts.clustering.

from analysis import GAS_TYPE, load, premium_matrix, price_matrix  # noqa: E402
from scripts.clustering import Params, _merge_small, _split_large, build_graph  # noqa: E402

OUT_DIR: Path = HERE / "output"
TARGET_CLUSTERS: int = 19  # The target used by freeze_clusters.py.
HOURS_PER_BIN: int = 2  # Runs per hourly bin (a run is every 30 minutes, so 2 per hour).

# (method, weight) pairs to try. The weight multiplies the price part of the feature, relative to the kilometre coordinates.
VARIANTS: list[tuple[str, float]] = [
    ("geography", 0.0),
    ("snapshot", 1.5),
    ("snapshot", 3.0),
    ("level", 1.5),
    ("level", 3.0),
    ("trajectory", 1.5),
    ("trajectory", 3.0),
    ("trajectory", 6.0),
    ("shape", 3.0),
    ("shape", 6.0),
    ("shape", 10.0),
]


def smooth(values: np.ndarray, neighbours: np.ndarray) -> np.ndarray:
    """
    Replaces each station's value with the median over its nearest stations, so one odd station cannot steer the clusters.

    Parameters
    ----------
    values : numpy.ndarray
        Array of shape (stations,) or (stations, times).
    neighbours : numpy.ndarray
        Indices of each station's nearest stations (including itself), shape (stations, k).

    Returns
    -------
    numpy.ndarray
        Smoothed values with the same shape as `values`.
    """
    return np.median(values[neighbours], axis=1)


def build_features(method: str, weight: float, premium: pd.DataFrame, xy: np.ndarray, neighbours: np.ndarray, clip: float) -> np.ndarray:
    """
    Builds the matrix Ward linkage clusters on.

    Parameters
    ----------
    method : str
        ``geography`` (no prices), ``snapshot`` (last run only, today's method), ``level`` (average premium over the window),
        ``trajectory`` (hourly premium, level included) or ``shape`` (hourly premium minus each station's average).
    weight : float
        Multiplier for the price part. Trajectory columns are divided by the square root of their number, so the weight reads as the
        RMS premium difference in cents whatever the window length.
    premium : pandas.DataFrame
        Premium over the market median, one row per station and one column per run.
    xy : numpy.ndarray
        Projected station coordinates in km, shape (stations, 2).
    neighbours : numpy.ndarray
        Nearest-station indices for `smooth`.
    clip : float
        Premiums are clipped to ±`clip` cents before smoothing.

    Returns
    -------
    numpy.ndarray
        Feature matrix with one row per station.

    Raises
    ------
    ValueError
        If `method` is not recognized.
    """
    values = np.clip(premium.to_numpy(), -clip, clip)
    if method == "geography":
        return xy
    if method == "snapshot":
        return np.c_[xy, weight * smooth(values[:, -1], neighbours)]
    if method == "level":
        return np.c_[xy, weight * smooth(values.mean(axis=1), neighbours)]

    # Hourly bins keep the feature small and remove the 30-minute noise from the fetch timing.
    hours = values.shape[1] // HOURS_PER_BIN
    hourly = values[:, : hours * HOURS_PER_BIN].reshape(len(values), hours, HOURS_PER_BIN).mean(axis=2)
    hourly = smooth(hourly, neighbours)
    if method == "trajectory":
        return np.c_[xy, weight * hourly / np.sqrt(hours)]
    if method == "shape":
        return np.c_[xy, weight * (hourly - hourly.mean(axis=1, keepdims=True)) / np.sqrt(hours)]
    raise ValueError(f"Unknown method {method!r}")


def cluster(stations: pd.DataFrame, features: np.ndarray, p: Params) -> np.ndarray:
    """
    Clusters stations like ``scripts.clustering.fit`` does, but on a given feature matrix.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations with ``x_km``, ``y_km`` and ``region`` columns.
    features : numpy.ndarray
        Feature matrix, one row per station.
    p : Params
        Clustering parameters, including the Ward threshold.

    Returns
    -------
    numpy.ndarray
        Cluster label per station; -1 for unclustered stations.
    """
    adjacency = build_graph(stations, p)
    n_components, component = connected_components(adjacency, directed=False)
    labels = np.full(len(stations), -1)
    next_id = 0

    # Each connected group is clustered on its own; groups below the minimum size stay unclustered (rural stations).
    for c in range(n_components):
        members = np.where(component == c)[0]
        if len(members) < p.min_size:
            continue
        sub = adjacency[members][:, members]
        model = AgglomerativeClustering(
            n_clusters=None, distance_threshold=p.threshold, linkage="ward", connectivity=sub, compute_full_tree=True)
        part = model.fit_predict(features[members])
        part = _merge_small(part, sub, features[members], p.min_size)
        part = _split_large(part, sub, features[members], p.min_size, p.max_size)
        for label in np.unique(part[part >= 0]):
            labels[members[part == label]] = next_id
            next_id += 1
    return labels


def cluster_to_target(stations: pd.DataFrame, features: np.ndarray, p: Params, target: int) -> np.ndarray:
    """
    Searches the Ward threshold so the clustering has about `target` clusters.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations with ``x_km``, ``y_km`` and ``region`` columns.
    features : numpy.ndarray
        Feature matrix, one row per station.
    p : Params
        Base clustering parameters; the threshold is overwritten.
    target : int
        Desired number of clusters.

    Returns
    -------
    numpy.ndarray
        Labels of the attempt that came closest to `target`.
    """
    low, high = 1.0, 5000.0
    best: tuple[int, np.ndarray] | None = None
    for _ in range(18):
        mid = (low * high) ** 0.5
        q = copy.copy(p)
        q.threshold = mid
        labels = cluster(stations, features, q)
        count = labels.max() + 1
        if best is None or abs(count - target) < abs(len(np.unique(best[1][best[1] >= 0])) - target):
            best = (mid, labels)
        if count > target:
            low = mid
        elif count < target:
            high = mid
        else:
            break
    assert best is not None
    return best[1]


def score(labels: np.ndarray, premium: pd.DataFrame, xy: np.ndarray) -> dict[str, float]:
    """
    Scores a clustering on a window of prices.

    ``shape_r2`` is the share of the variance of stations' movement (premium minus its own average) that cluster membership explains.
    ``level_r2`` is the same for the average premium. ``corr`` is the mean correlation of movement between stations in the same cluster.

    Parameters
    ----------
    labels : numpy.ndarray
        Cluster label per station; -1 stations are ignored.
    premium : pandas.DataFrame
        Premium over the market median in the window being scored.
    xy : numpy.ndarray
        Projected coordinates in km.

    Returns
    -------
    dict[str, float]
        Metrics ``shape_r2``, ``level_r2``, ``corr``, ``median_diameter_km``, ``max_diameter_km``, ``clusters``, ``unclustered``.
    """
    keep = labels >= 0
    values = premium.to_numpy()
    level = values.mean(axis=1, keepdims=True)
    movement = values - level

    def r_squared(matrix: np.ndarray) -> float:
        total = ((matrix[keep] - matrix[keep].mean(axis=0)) ** 2).sum()
        within = sum(((matrix[labels == c] - matrix[labels == c].mean(axis=0)) ** 2).sum() for c in np.unique(labels[keep]))
        return 1 - within / total

    correlations, diameters = [], []
    for c in np.unique(labels[keep]):
        group = movement[labels == c]
        group = group - group.mean(axis=1, keepdims=True)
        norm = np.linalg.norm(group, axis=1) + 1e-9
        corr = (group @ group.T) / norm[:, None] / norm[None]
        correlations.append((corr.sum() - len(group)) / (len(group) * (len(group) - 1)))
        diameters.append(np.hypot(np.ptp(xy[labels == c, 0]), np.ptp(xy[labels == c, 1])))
    return {
        "shape_r2": r_squared(movement), "level_r2": r_squared(level), "corr": float(np.mean(correlations)),
        "median_diameter_km": float(np.median(diameters)), "max_diameter_km": float(np.max(diameters)),
        "clusters": int(len(diameters)), "unclustered": int((~keep).sum()),
    }


def main() -> None:
    """
    Runs every variant in both split directions and writes the results.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    stations, runs, changes = load()
    prices = price_matrix(stations, runs, changes, GAS_TYPE)

    # --- Prepare the station table the project's graph builder expects -----------------
    stations = stations.loc[prices.index].reset_index()
    xy = stations[["x_km", "y_km"]].to_numpy()
    p = Params()
    neighbours = cKDTree(xy).query(xy, k=p.smooth_k)[1]

    # --- Two folds: fit on the first half and score on the second, then the reverse -----
    half = prices.shape[1] // 2
    folds = {"early→late": (slice(0, half), slice(half, None)), "late→early": (slice(half, None), slice(0, half))}
    rows = []
    for fold, (fit_window, test_window) in folds.items():
        fit_premium = premium_matrix(prices.iloc[:, fit_window])
        test_premium = premium_matrix(prices.iloc[:, test_window])
        for method, weight in VARIANTS:
            features = build_features(method, weight, fit_premium, xy, neighbours, p.clip)
            labels = cluster_to_target(stations, features, p, TARGET_CLUSTERS)
            rows.append({"fold": fold, "method": method, "weight": weight,
                         **{f"in_{k}": v for k, v in score(labels, fit_premium, xy).items()},
                         **{f"out_{k}": v for k, v in score(labels, test_premium, xy).items()}})
            print(f"{fold:11s} {method:10s} w={weight:<4} out shape R2 {rows[-1]['out_shape_r2']:.3f} level R2 {rows[-1]['out_level_r2']:.3f}")

    # --- Report: average the two folds, since either one alone depends on which half holds the midnight jump ---
    results = pd.DataFrame(rows)
    results.to_csv(OUT_DIR / "ward_results.csv", index=False, float_format="%.4f")
    mean = results.groupby(["method", "weight"], sort=False).mean(numeric_only=True).reset_index()
    lines = [
        "# Ward experiment\n",
        f"{len(stations)} stations, about {TARGET_CLUSTERS} clusters, graph and size limits from `Params()`. Scores are averaged over the "
        "two folds (fit on one half of the window, score on the other).\n",
        "| Method | Weight | In-sample shape R² | **Out-of-sample shape R²** | **Out-of-sample level R²** | Out-of-sample corr "
        "| Median / max diameter (km) | Clusters | Unclustered |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in mean.itertuples():
        lines.append(f"| {r.method} | {r.weight:g} | {r.in_shape_r2:.3f} | **{r.out_shape_r2:.3f}** | **{r.out_level_r2:.3f}** | "
                     f"{r.out_corr:.2f} | {r.out_median_diameter_km:.0f} / {r.out_max_diameter_km:.0f} | {r.out_clusters:.0f} "
                     f"| {r.out_unclustered:.0f} |")

    # --- How different are the clusters themselves? -----------------------------------
    # Fit each method on the whole window and compare memberships with the adjusted Rand index (1 = identical, 0 = unrelated).
    full_premium = premium_matrix(prices)
    chosen = [("geography", 0.0), ("snapshot", 1.5), ("level", 3.0), ("trajectory", 3.0), ("shape", 6.0)]
    full = {m: cluster_to_target(stations, build_features(m, w, full_premium, xy, neighbours, p.clip), p, TARGET_CLUSTERS)
            for m, w in chosen}
    lines += ["", "## Agreement between clusterings fitted on the whole window\n",
              "Adjusted Rand index between each pair (1 = same clusters). Stations unclustered in both are ignored.\n",
              "| | " + " | ".join(full) + " |", "|---|" + "---|" * len(full)]
    for a, la in full.items():
        cells = []
        for b, lb in full.items():
            keep = (la >= 0) | (lb >= 0)
            cells.append(f"{adjusted_rand_score(la[keep], lb[keep]):.2f}")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")
    (OUT_DIR / "ward_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
