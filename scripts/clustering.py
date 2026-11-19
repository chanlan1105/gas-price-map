"""Data-driven, spatially-contiguous clustering of gas stations.

Stations are clustered with Ward linkage restricted to a k-nearest-neighbour graph, so clusters are contiguous. Small or
isolated groups (rural stations) are left unclustered (cluster = -1).

Two kinds of features are supported:

* **History (the default for freezing)**: ``(x_km, y_km, history_weight * hourly premium trajectory / sqrt(hours))`` over the
  most recent days of stored prices (see `load_history_fit`). Stations that trend together end up together, and the result does
  not depend on the time of day at which the fit is run.
* **Snapshot**: ``(x_km, y_km, alpha * premium)`` from the current feed only. Kept for comparison and for previews without a history.
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from sklearn.cluster import AgglomerativeClustering

# The region bounds live in interactive_map.py so the map and the clustering always select the same stations.
from scripts import history
from scripts.interactive_map import REGIONS

LAT0 = 45.5  # Reference latitude for the Greater Montreal projection.


def load_stations(path: str, gas_type: str = "Régulier") -> pd.DataFrame:
    """Loads station data from a GeoJSON file.

    Parameters
    ----------
    path : str
        Path to the GeoJSON station feed.
    gas_type : str, default="Régulier"
        Price column that must be present for a station to be retained.

    Returns
    -------
    pandas.DataFrame
        Parsed and filtered station data.

    Raises
    ------
    OSError
        If the GeoJSON file cannot be opened.
    json.JSONDecodeError
        If the file does not contain valid JSON.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return load_stations_data(data, gas_type)


def load_stations_data(data: dict, gas_type: str = "Régulier") -> pd.DataFrame:
    """Loads and filters stations from decoded GeoJSON data.

    Parameters
    ----------
    data : dict
        Decoded GeoJSON feature collection.
    gas_type : str, default="Régulier"
        Price column that must be present for a station to be retained.

    Returns
    -------
    pandas.DataFrame
        Parsed and filtered station data with derived clustering columns.

    Raises
    ------
    KeyError
        If the decoded GeoJSON does not contain the expected feature fields.
    """
    feats = data["features"]
    rows = []
    for f in feats:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        prices = {
            i["GasType"]: float(i["Price"].replace("¢", "")) if isinstance(i["Price"], str) else np.nan
            for i in p["Prices"]
        }
        rows.append(dict(name=p["Name"], brand=p["brand"], address=p["Address"], pc=p.get("PostalCode") or "",
                         region=p["Region"], lon=lon, lat=lat, **prices))
    df = pd.DataFrame(rows)

    keep = pd.Series(False, index=df.index)
    for region, bb in REGIONS.items():
        m = df.region == region
        if bb:
            m &= df.lat >= bb.get("lat_min", -90)
            m &= df.lat <= bb.get("lat_max", 90)
            m &= df.lon >= bb.get("lon_min", -180)
            m &= df.lon <= bb.get("lon_max", 180)
        keep |= m
    return add_station_columns(df[keep].dropna(subset=[gas_type]))


def add_station_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drops stations with invalid coordinates and adds the derived clustering columns.

    Parameters
    ----------
    df : pandas.DataFrame
        Stations with ``name``, ``address``, ``region``, ``lon`` and ``lat`` columns. A ``key`` column is kept if present.

    Returns
    -------
    pandas.DataFrame
        Valid stations with a fresh integer index and the ``key``, ``x_km``, ``y_km`` and ``city`` columns.
    """
    # Coordinate validation catches feed records that pass regional bounds despite
    # containing placeholder coordinates.
    bad = ~(df.lat.between(44.9, 62.6) & df.lon.between(-79.8, -57.0))
    if bad.any():
        print("Dropping stations with invalid coordinates:", df.loc[bad, ["name", "address", "region", "lat", "lon"]].to_dict("records"))
    df = df[~bad].reset_index(drop=True)

    # The feed has no stable identifier, so derive a repeatable station key (the history database supplies its own).
    if "key" not in df.columns:
        df["key"] = df.apply(lambda r: f"{r['name']}|{r.lon:.5f}|{r.lat:.5f}", axis=1)
    df["x_km"] = (df.lon + 73.6) * 111.32 * np.cos(np.radians(LAT0))
    df["y_km"] = (df.lat - LAT0) * 110.57
    df["city"] = df.address.fillna("").apply(_city)
    return df


def _city(addr: str) -> str:
    """Normalizes the city component of a station address.

    Parameters
    ----------
    addr : str
        Comma-separated station address.

    Returns
    -------
    str
        Normalized city name.
    """
    c = addr.split(",")[-1].strip() if "," in addr else ""
    c = re.sub(r"\s+", " ", c).title()
    c = re.sub(r"^St(e?)[- .]", lambda m: "Saint" + m.group(1) + "-", c)
    return c.replace(" Sur ", "-sur-").replace(" De ", "-de-").replace("-Sur-", "-sur-").replace("-De-", "-de-")


@dataclass
class Params:
    """Stores clustering parameters."""

    k: int = 6
    max_edge_km: float = 8.0
    alpha: float = 1.5  # Weight of the premium in snapshot features.
    history_weight: float = 3.0  # Weight of the premium trajectory in history features, as an RMS premium difference in cents.
    min_coverage: float = 0.5  # Share of the window's hours a station needs a price for to take part in a history fit.
    threshold: float = 40.0
    min_size: int = 12
    same_region: bool = True
    linked_regions: tuple = (("Laurentides", "Lanaudière"),)
    max_size: int = 75
    smooth_k: int = 7
    clip: float = 15.0


def build_graph(df: pd.DataFrame, p: Params):
    """Builds the spatial connectivity graph for station records.

    Parameters
    ----------
    df : pandas.DataFrame
        Station data containing projected coordinates and regions.
    p : Params
        Clustering parameters.

    Returns
    -------
    scipy.sparse.csr_matrix
        Symmetric binary station connectivity matrix.
    """
    xy = df[["x_km", "y_km"]].to_numpy()
    n = len(df)
    rows, cols = [], []
    link = {r: g[0] for g in p.linked_regions for r in g}
    gkey = df.region.map(lambda r: link.get(r, r))
    groups = gkey.groupby(gkey).indices if p.same_region else {"all": np.arange(n)}
    for idx in groups.values():
        if len(idx) < 2:
            continue
        tree = cKDTree(xy[idx])
        kk = min(p.k + 1, len(idx))
        dist, nb = tree.query(xy[idx], k=kk)
        for a in range(len(idx)):
            for d, b in zip(dist[a][1:], nb[a][1:]):
                if d <= p.max_edge_km:
                    rows.append(idx[a]); cols.append(idx[b])
    A = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n)).tocsr()
    return ((A + A.T) > 0).astype(int).tocsr()


def hourly_premium(prices: np.ndarray) -> np.ndarray:
    """Subtracts the market median from every hour of every station's price series.

    Parameters
    ----------
    prices : numpy.ndarray
        Prices of shape (stations, hours) with NaN where a station had no known price.

    Returns
    -------
    numpy.ndarray
        Premium over the median of all stations at the same hour, same shape. The market-wide cycle cancels out.
    """
    with warnings.catch_warnings():
        # An hour with no prices at all is possible at the start of a short history.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return prices - np.nanmedian(prices, axis=0, keepdims=True)


def _fill_rows(values: np.ndarray) -> np.ndarray:
    """Replaces missing hours with each station's own average premium, so they carry no movement.

    Parameters
    ----------
    values : numpy.ndarray
        Premium of shape (stations, hours), NaN where unknown. Every row needs at least one known value.

    Returns
    -------
    numpy.ndarray
        Copy of `values` without NaN.
    """
    out = values.copy()
    row_mean = np.nanmean(out, axis=1, keepdims=True)
    return np.where(np.isnan(out), row_mean, out)


def history_features(premium: np.ndarray, xy: np.ndarray, p: Params) -> np.ndarray:
    """Builds the Ward feature matrix from the hourly premium trajectories.

    Premiums are clipped to ±`Params.clip` cents and smoothed per hour with the median of the `Params.smooth_k` nearest stations,
    so single outlier stations cannot steer the clusters. The trajectory is divided by the square root of the number of hours, so
    `Params.history_weight` is the RMS premium difference in cents that counts as much as one kilometre, whatever the window length.

    Parameters
    ----------
    premium : numpy.ndarray
        Premium of shape (stations, hours), NaN where unknown. Every row needs at least one known value.
    xy : numpy.ndarray
        Projected coordinates in kilometres, shape (stations, 2).
    p : Params
        Clustering parameters.

    Returns
    -------
    numpy.ndarray
        Feature matrix of shape (stations, 2 + hours).
    """
    values = np.clip(_fill_rows(premium), -p.clip, p.clip)
    if p.smooth_k > 0:
        _, nb = cKDTree(xy).query(xy, k=min(p.smooth_k, len(xy)))
        values = np.median(values[nb], axis=1)
    return np.c_[xy, p.history_weight * values / np.sqrt(values.shape[1])]


def fit(df: pd.DataFrame, gas_type: str, p: Params, premium: np.ndarray | None = None) -> pd.DataFrame:
    """Fits contiguous price-based clusters to station data.

    Parameters
    ----------
    df : pandas.DataFrame
        Station data returned by a loader.
    gas_type : str
        Price column used to calculate the snapshot feature and reported in the quality table.
    p : Params
        Clustering parameters.
    premium : numpy.ndarray, optional
        Hourly premium of shape (stations, hours) in the row order of `df` (see `load_history_fit`). When given, the clusters are
        fitted on these trajectories; otherwise on the snapshot in the `gas_type` column.

    Returns
    -------
    pandas.DataFrame
        Copy of the input data with ``premium``, ``feature``, ``fitted`` and ``cluster`` columns. With `premium`, stations with
        too few priced hours (`Params.min_coverage`) are not fitted: ``fitted`` is False and their cluster is -1.
    """
    df = df.copy()
    df["premium"] = df[gas_type] - df[gas_type].median()
    xy_all = df[["x_km", "y_km"]].to_numpy()

    # --- Choose the stations that take part and build their features --------------------
    if premium is None:
        fitted = np.ones(len(df), dtype=bool)
        feat = df.premium.clip(-p.clip, p.clip).to_numpy()
        if p.smooth_k > 0:
            _, nb = cKDTree(xy_all).query(xy_all, k=min(p.smooth_k, len(df)))
            feat = np.median(feat[nb], axis=1)
        X = np.c_[df.x_km, df.y_km, p.alpha * feat]
    else:
        # Stations with a patchy history are placed later by proximity instead of steering the clusters.
        fitted = (~np.isnan(premium)).mean(axis=1) >= p.min_coverage
        X = history_features(premium[fitted], xy_all[fitted], p)
        with warnings.catch_warnings():
            # A station that never had a price is not fitted, so its all-NaN row is expected.
            warnings.simplefilter("ignore", category=RuntimeWarning)
            feat = np.nanmean(premium, axis=1)
        df["premium"] = feat
    df["feature"] = feat
    df["fitted"] = fitted

    # --- Cluster the stations that take part -------------------------------------------
    sub_df = df[fitted].reset_index(drop=True)
    labels_sub = _cluster(sub_df, X, p)
    labels = np.full(len(df), -1)
    labels[fitted] = labels_sub
    df["cluster"] = labels
    return df


def _cluster(df: pd.DataFrame, X: np.ndarray, p: Params) -> np.ndarray:
    """Clusters stations on a feature matrix: graph, Ward linkage, small-cluster merge and size cap.

    Parameters
    ----------
    df : pandas.DataFrame
        Stations with ``x_km``, ``y_km`` and ``region`` columns, in the row order of `X`.
    X : numpy.ndarray
        Feature matrix, one row per station.
    p : Params
        Clustering parameters.

    Returns
    -------
    numpy.ndarray
        Cluster label per station; -1 for unclustered stations.
    """
    A = build_graph(df, p)
    ncomp, comp = connected_components(A, directed=False)

    labels = np.full(len(df), -1)
    next_id = 0
    for c in range(ncomp):
        idx = np.where(comp == c)[0]
        if len(idx) < p.min_size:
            continue
        sub = A[idx][:, idx]
        model = AgglomerativeClustering(
            n_clusters=None, distance_threshold=p.threshold, linkage="ward",
            connectivity=sub, compute_full_tree=True)
        lab = model.fit_predict(X[idx])
        lab = _merge_small(lab, sub, X[idx], p.min_size)
        lab = _split_large(lab, sub, X[idx], p.min_size, p.max_size)
        for l in np.unique(lab):
            if l < 0:
                continue
            labels[idx[lab == l]] = next_id
            next_id += 1
    return labels


def _split_large(lab, A, X, min_size, max_size):
    """Splits oversized clusters into contiguous pieces.

    Parameters
    ----------
    lab : numpy.ndarray
        Cluster labels.
    A : scipy.sparse.spmatrix
        Connectivity matrix.
    X : numpy.ndarray
        Clustering features.
    min_size : int
        Minimum permitted cluster size.
    max_size : int
        Maximum permitted cluster size.

    Returns
    -------
    numpy.ndarray
        Updated cluster labels.
    """
    lab = lab.copy()
    queue = [l for l in np.unique(lab) if l >= 0]
    next_label = lab.max() + 1
    while queue:
        l = queue.pop()
        members = np.where(lab == l)[0]
        if len(members) <= max_size:
            continue
        sub = A[members][:, members]
        k0 = int(np.ceil(len(members) / (0.7 * max_size)))
        for k in range(k0, k0 + 8):
            part = AgglomerativeClustering(n_clusters=k, linkage="ward", connectivity=sub).fit_predict(X[members])
            part = _merge_small(part, sub, X[members], min_size)
            ids = [i for i in np.unique(part) if i >= 0]
            if len(ids) >= 2 and not (part < 0).any():
                break
        else:
            continue
        for i in ids[1:]:
            lab[members[part == i]] = next_label
            queue.append(next_label)
            next_label += 1
        queue.append(l)
    return lab


def _merge_small(lab, A, X, min_size):
    """Merges undersized clusters into adjacent nearest-centroid clusters.

    Parameters
    ----------
    lab : numpy.ndarray
        Cluster labels.
    A : scipy.sparse.spmatrix
        Connectivity matrix.
    X : numpy.ndarray
        Clustering features.
    min_size : int
        Minimum permitted cluster size.

    Returns
    -------
    numpy.ndarray
        Updated cluster labels.
    """
    lab = lab.copy()
    while True:
        ids, counts = np.unique(lab[lab >= 0], return_counts=True)
        small = [i for i, c in zip(ids, counts) if c < min_size]
        if not small:
            return lab
        s = min(small, key=lambda i: (lab == i).sum())
        members = np.where(lab == s)[0]
        nb_labels = set(lab[A[members].indices]) - {s, -1}
        if not nb_labels:
            lab[members] = -1
            continue
        cen = X[members].mean(0)
        best = min(nb_labels, key=lambda l: np.linalg.norm(X[lab == l].mean(0) - cen))
        lab[members] = best


# Local names for areas of the Montréal island, as (lon, lat) reference points. Clusters are matched to the nearest
# unused point, so names stay stable as long as the cluster geography does.
ISLAND_ANCHORS = {
    "West Island": (-73.84, 45.47),
    "Centre-Ouest": (-73.72, 45.50),
    "Sud-Ouest": (-73.62, 45.47),
    "Centre-Ville": (-73.57, 45.50),
    "Centre-Est": (-73.60658, 45.56242),
    "Nord": (-73.62694, 45.60453),
    "Est": (-73.54, 45.62),
}

# A cluster also takes the name of a second area when at least this share of its island stations is nearest to it.
ISLAND_MIN_SHARE = 0.25
# Maximum number of area names in one island cluster name.
ISLAND_MAX_NAMES = 2

_COMPASS = ["Est", "Nord-Est", "Nord", "Nord-Ouest", "Ouest", "Sud-Ouest", "Sud", "Sud-Est"]


def _compass(dx: float, dy: float, centre_km: float = 3.0) -> str:
    """Converts a displacement into a compass direction.

    Parameters
    ----------
    dx, dy : float
        East-west and north-south displacement in kilometres.
    centre_km : float, default=3.0
        Radius classified as the centre.

    Returns
    -------
    str
        Compass direction label.
    """
    if np.hypot(dx, dy) < centre_km:
        return "Centre"
    ang = (np.degrees(np.arctan2(dy, dx)) + 360 + 22.5) % 360
    return _COMPASS[int(ang // 45)]


def _island_names(df: pd.DataFrame, island: list[int]) -> dict[int, list[str]]:
    """Matches island clusters to the local area names in `ISLAND_ANCHORS`.

    Parameters
    ----------
    df : pandas.DataFrame
        Clustered station data.
    island : list[int]
        Identifiers of the clusters located mostly on the Montréal island.

    Returns
    -------
    dict[int, list[str]]
        Mapping from cluster identifier to its area names, most common area first. Each cluster has
        one primary name, unique across clusters, plus a second name when a substantial share of its
        stations lies nearer to another area (see `ISLAND_MIN_SHARE`). Clusters beyond the number of
        anchors fall back to compass names.
    """
    # --- Project the anchors and cluster centroids into the same km grid ---------------
    anchors = list(ISLAND_ANCHORS.items())
    ax = np.array([(lon + 73.6) * 111.32 * np.cos(np.radians(LAT0)) for _, (lon, _) in anchors])
    ay = np.array([(lat - LAT0) * 110.57 for _, (_, lat) in anchors])
    cen = np.array([[df.x_km[df.cluster == c].mean(), df.y_km[df.cluster == c].mean()] for c in island])
    dist = np.hypot(cen[:, [0]] - ax[None, :], cen[:, [1]] - ay[None, :])

    # --- Assign one anchor per cluster, minimizing total distance ----------------------
    # A one-to-one assignment prevents two clusters from sharing a primary name such as "Ouest".
    rows, cols = linear_sum_assignment(dist)
    primary = {island[r]: c for r, c in zip(rows, cols)}

    # --- Fall back to compass names for any unmatched cluster --------------------------
    isl = df[df.region == "Montréal"]
    names: dict[int, dict[str, float]] = {}  # cluster -> {area name: share of its island stations}
    for c in island:
        g = df[(df.cluster == c) & (df.region == "Montréal")]
        if c not in primary:
            gc = df[df.cluster == c]
            names[c] = {_compass(gc.x_km.mean() - isl.x_km.median(), gc.y_km.mean() - isl.y_km.median()): 1.0}
            continue

        # --- Each island station votes for its nearest anchor, giving the share per area -----
        nearest = np.hypot(g.x_km.to_numpy()[:, None] - ax[None, :], g.y_km.to_numpy()[:, None] - ay[None, :]).argmin(axis=1)
        shares = np.bincount(nearest, minlength=len(anchors)) / max(len(g), 1)
        found = {anchors[primary[c]][0]: shares[primary[c]]}

        # --- A cluster that straddles a second area keeps that name too -------------------
        others = [i for i in np.argsort(-shares) if i != primary[c] and shares[i] >= ISLAND_MIN_SHARE]
        for i in others[:ISLAND_MAX_NAMES - 1]:
            found[anchors[i][0]] = shares[i]
        names[c] = found

    # --- Order each cluster's names by share, so the dominant area comes first ----------
    ordered = {c: sorted(found, key=lambda n: -found[n])[:ISLAND_MAX_NAMES] for c, found in names.items()}
    # --- A cluster split exactly between Centre-Est and Centre-Ouest is simply "Centre" -
    for c, lst in ordered.items():
        if set(lst) == {"Centre-Est", "Centre-Ouest"}:
            ordered[c] = ["Centre"]
    return ordered


# Minimum share of Montréal-region stations for a cluster to count as being on the island.
ISLAND_CLUSTER_SHARE = 0.6


def island_clusters(df: pd.DataFrame) -> list[int]:
    """Finds the clusters located mostly on the Montréal island.

    Parameters
    ----------
    df : pandas.DataFrame
        Clustered station data.

    Returns
    -------
    list[int]
        Identifiers of the clusters where at least `ISLAND_CLUSTER_SHARE` of the stations are in the Montréal region.
    """
    clusters = df[df.cluster >= 0].groupby("cluster")
    return [c for c, g in clusters if (g.region == "Montréal").mean() >= ISLAND_CLUSTER_SHARE]


def label_clusters(df: pd.DataFrame, min_city_share: float = 0.1, max_cities: int = 2) -> dict[int, str]:
    """Assigns human-readable names to station clusters.

    Parameters
    ----------
    df : pandas.DataFrame
        Clustered station data.
    min_city_share : float, default=0.2
        Minimum fraction of a cluster's stations a municipality needs to appear in its name. The most
        common municipality is always included.
    max_cities : int, default=2
        Maximum number of municipalities in a name.

    Returns
    -------
    dict[int, str]
        Mapping from cluster identifier to display name.
    """
    clusters = df[df.cluster >= 0].groupby("cluster")
    island = island_clusters(df)
    island_names = _island_names(df, island) if island else {}
    names, used = {}, {}
    for c, g in clusters:
        if c in island_names:
            name = f"Montréal ({' / '.join(island_names[c])})"
        else:
            # Municipalities with only a station or two are noise, so name the cluster after the
            # significant ones (share of the cluster's stations, not of the named ones).
            top = g.city.replace("", np.nan).dropna().value_counts()
            significant = top[top / len(g) >= min_city_share].index[:max_cities]
            name = " / ".join(significant) if len(significant) else (top.index[0] if len(top) else f"Cluster {c}")
        used[name] = used.get(name, 0) + 1
        names[c] = name if used[name] == 1 else f"{name} {used[name]}"
    return names


def _mean_pair_correlation(movement: np.ndarray) -> float:
    """Averages the correlation of movement between every pair of stations in a group.

    Parameters
    ----------
    movement : numpy.ndarray
        Premium minus each station's own average, shape (stations, hours), without NaN.

    Returns
    -------
    float
        Mean pairwise correlation; NaN for a group of fewer than two stations.
    """
    if len(movement) < 2:
        return float("nan")
    centred = movement - movement.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(centred, axis=1) + 1e-9
    corr = (centred @ centred.T) / norm[:, None] / norm[None]
    return float((corr.sum() - len(centred)) / (len(centred) * (len(centred) - 1)))


def report(df: pd.DataFrame, gas_type: str, premium: np.ndarray | None = None) -> pd.DataFrame:
    """Summarizes quality metrics for each cluster.

    Parameters
    ----------
    df : pandas.DataFrame
        Clustered station data.
    gas_type : str
        Price column to summarize.
    premium : numpy.ndarray, optional
        Hourly premium in the row order of `df`. When given, the table gains a ``corr`` column with the mean correlation of
        movement between the stations of each cluster, the property the cluster's average line relies on.

    Returns
    -------
    pandas.DataFrame
        Per-cluster count, region, price, and diameter metrics.
    """
    g = df[df.cluster >= 0].groupby("cluster")
    out = pd.DataFrame({
        "n": g.size(),
        "region": g.region.agg(lambda s: s.mode().iat[0]),
        "median": g[gas_type].median().round(1),
        "iqr": g[gas_type].agg(lambda s: s.quantile(.75) - s.quantile(.25)).round(1),
        "max_dev": g[gas_type].agg(lambda s: (s - s.median()).abs().max()).round(1),
        "diam_km": g.apply(lambda s: np.hypot(np.ptp(s.x_km), np.ptp(s.y_km))).round(1),
    })
    if premium is not None:
        # Clustered stations always have enough priced hours (`Params.min_coverage`), so their rows can be filled.
        clustered = df[df.cluster >= 0].groupby("cluster")
        out["corr"] = [round(_mean_pair_correlation(_fill_rows(premium[g.index.to_numpy()])), 2) for _, g in clustered]
    return out


def variance_explained(df: pd.DataFrame, gas_type: str) -> float:
    """Calculates the price variance explained by cluster assignments.

    Parameters
    ----------
    df : pandas.DataFrame
        Clustered station data.
    gas_type : str
        Price column to evaluate.

    Returns
    -------
    float
        Fraction of total price variance explained within clusters.
    """
    d = df[df.cluster >= 0]
    tot = ((d[gas_type] - d[gas_type].mean()) ** 2).sum()
    within = d.groupby("cluster")[gas_type].apply(lambda s: ((s - s.mean()) ** 2).sum()).sum()
    return 1 - within / tot


def fit_target(df, gas_type, p: Params, target_k: int, premium: np.ndarray | None = None):
    """Finds a Ward threshold that produces a target cluster count.

    Parameters
    ----------
    df : pandas.DataFrame
        Station data to cluster.
    gas_type : str
        Price column used for clustering.
    p : Params
        Base clustering parameters.
    target_k : int
        Desired number of clusters.
    premium : numpy.ndarray, optional
        Hourly premium for a history fit; see `fit`.

    Returns
    -------
    tuple
        Best clustered data, achieved cluster count, and Ward threshold.
    """
    lo, hi = 1.0, 5000.0
    best = None
    for _ in range(18):
        mid = (lo * hi) ** 0.5
        q = copy.copy(p); q.threshold = mid
        d = fit(df, gas_type, q, premium)
        k = d.cluster.max() + 1
        if best is None or abs(k - target_k) < abs(best[1] - target_k):
            best = (d, k, mid)
        if k > target_k:
            lo = mid
        elif k < target_k:
            hi = mid
        else:
            break
    return best


def load_history_fit(conn: sqlite3.Connection, days: int, gas_type: str = "Régulier") -> tuple[pd.DataFrame, np.ndarray]:
    """Loads the stations and hourly premiums for a history fit from the database.

    Only stations still in the latest run are returned. The ``gas_type`` column of the result holds each station's latest known price.

    Parameters
    ----------
    conn : sqlite3.Connection
        Connection from `history.connect`.
    days : int
        Window length: the most recent `days` days, or all the history there is if less.
    gas_type : str, default="Régulier"
        Fuel to fit on.

    Returns
    -------
    stations : pandas.DataFrame
        Stations with the columns the loaders give, plus ``key`` (the history key).
    premium : numpy.ndarray
        Hourly premium of shape (stations, hours) in the row order of `stations`; NaN where a station had no known price.

    Raises
    ------
    ValueError
        If no run has been recorded.
    """
    grid = history.fit_grid(conn, days)
    if grid is None:
        raise ValueError("The history database has no runs.")
    stations, prices = history.hourly_prices(conn, gas_type, grid)
    keys = {sid: key for sid, key in conn.execute("SELECT id, key FROM stations")}
    stations["key"] = stations["id"].map(keys)

    # Forward filling means a station that stopped selling this fuel keeps its last known price.
    stations[gas_type] = pd.DataFrame(prices).ffill(axis=1).iloc[:, -1].to_numpy()

    # Drop invalid coordinates with the same rule as the feed loader, keeping the matrix rows aligned.
    valid = stations.lat.between(44.9, 62.6) & stations.lon.between(-79.8, -57.0)
    return add_station_columns(stations[valid]), hourly_premium(prices[valid.to_numpy()])


def cluster_quality(labels: np.ndarray, premium: np.ndarray) -> dict[str, float]:
    """Scores a clustering on a window of premiums.

    ``shape_r2`` is the share of the variance of stations' movement (premium minus their own average) that cluster membership
    explains: do the stations of a cluster move alike? ``level_r2`` is the same for the average premium. ``corr`` is the mean
    correlation of movement between stations of the same cluster.

    Parameters
    ----------
    labels : numpy.ndarray
        Cluster label per station; -1 stations are ignored.
    premium : numpy.ndarray
        Hourly premium of shape (stations, hours), rows aligned with `labels`. Rows without any known value are ignored.

    Returns
    -------
    dict[str, float]
        Metrics ``shape_r2``, ``level_r2`` and ``corr``.
    """
    keep = (labels >= 0) & (~np.isnan(premium)).any(axis=1)
    values = _fill_rows(premium[keep])
    labs = labels[keep]
    level = values.mean(axis=1, keepdims=True)
    movement = values - level

    def r_squared(matrix: np.ndarray) -> float:
        total = ((matrix - matrix.mean(axis=0)) ** 2).sum()
        within = sum(((matrix[labs == c] - matrix[labs == c].mean(axis=0)) ** 2).sum() for c in np.unique(labs))
        return float(1 - within / total)

    corr = [_mean_pair_correlation(movement[labs == c]) for c in np.unique(labs)]
    return {"shape_r2": r_squared(movement), "level_r2": r_squared(level), "corr": float(np.nanmean(corr))}


def quality_lines(df: pd.DataFrame, gas_type: str, p: Params, target_k: int, premium: np.ndarray) -> list[str]:
    """Describes how well a history fit holds up, in and out of sample.

    The in-sample scores use the fitted window. The out-of-sample scores refit on the first half of the window and score on the
    second half, then the reverse, and average the two.

    Parameters
    ----------
    df : pandas.DataFrame
        Output of `fit` on `premium`.
    gas_type : str
        Price column used by `fit`.
    p : Params
        Parameters of the fit; the threshold is searched again for each half.
    target_k : int
        Target number of clusters for the half fits.
    premium : numpy.ndarray
        Hourly premium used for the fit, rows aligned with `df`.

    Returns
    -------
    list[str]
        Lines to print.
    """
    inside = cluster_quality(df.cluster.to_numpy(), premium)
    half = premium.shape[1] // 2
    folds = []
    for fit_window, test_window in ((slice(0, half), slice(half, None)), (slice(half, None), slice(0, half))):
        trial, _, _ = fit_target(df, gas_type, p, target_k, premium[:, fit_window])
        folds.append(cluster_quality(trial.cluster.to_numpy(), premium[:, test_window]))
    outside = {k: float(np.mean([f[k] for f in folds])) for k in inside}
    fitted = int(df.fitted.sum())
    rural = int(((df.cluster < 0) & df.fitted).sum())
    return [
        f"History fit: {premium.shape[1]} hourly points, {fitted} of {len(df)} stations fitted ({rural} left unclustered), "
        f"{int(df.cluster.max()) + 1} clusters",
        f"  In sample:     shape R² {inside['shape_r2']:.3f}, level R² {inside['level_r2']:.3f}, within-cluster correlation {inside['corr']:.2f}",
        f"  Out of sample: shape R² {outside['shape_r2']:.3f}, level R² {outside['level_r2']:.3f}, within-cluster correlation {outside['corr']:.2f}"
        " (fitted on one half, scored on the other)",
    ]
