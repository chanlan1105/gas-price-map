"""Prototype: data-driven, spatially-contiguous clustering of gas stations.

Stations are clustered on (x_km, y_km, alpha * price_premium) with Ward linkage
restricted to a k-nearest-neighbour graph, so clusters are contiguous. Small or
isolated groups (rural stations) are left unclustered (cluster = -1).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from sklearn.cluster import AgglomerativeClustering

# The region bounds live in interactive_map.py so the map and the clustering always select the same stations.
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
    df = df[keep].dropna(subset=[gas_type])
    # Coordinate validation catches feed records that pass regional bounds despite
    # containing placeholder coordinates.
    bad = ~(df.lat.between(44.9, 62.6) & df.lon.between(-79.8, -57.0))
    if bad.any():
        print("Dropping stations with invalid coordinates:", df.loc[bad, ["name", "address", "region", "lat", "lon"]].to_dict("records"))
    df = df[~bad].reset_index(drop=True)

    # The feed has no stable identifier, so derive a repeatable station key.
    df["key"] = df.apply(lambda r: f"{r['name']}|{r.lon:.5f}|{r.lat:.5f}", axis=1)
    df["x_km"] = (df.lon + 73.6) * 111.32 * np.cos(np.radians(LAT0))
    df["y_km"] = (df.lat - LAT0) * 110.57
    df["city"] = df.address.apply(_city)
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
    alpha: float = 1.5
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


def fit(df: pd.DataFrame, gas_type: str, p: Params) -> pd.DataFrame:
    """Fits contiguous price-based clusters to station data.

    Parameters
    ----------
    df : pandas.DataFrame
        Station data returned by a loader.
    gas_type : str
        Price column used to calculate the clustering feature.
    p : Params
        Clustering parameters.

    Returns
    -------
    pandas.DataFrame
        Copy of the input data with premium, feature, and cluster columns.
    """
    df = df.copy()
    df["premium"] = df[gas_type] - df[gas_type].median()
    feat = df.premium.clip(-p.clip, p.clip).to_numpy()
    if p.smooth_k > 0:
        xy = df[["x_km", "y_km"]].to_numpy()
        _, nb = cKDTree(xy).query(xy, k=min(p.smooth_k, len(df)))
        feat = np.median(feat[nb], axis=1)
    df["feature"] = feat
    X = np.c_[df.x_km, df.y_km, p.alpha * feat]
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
    df["cluster"] = labels
    return df


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
    "Nord": (-73.63, 45.58),
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
    return {c: sorted(found, key=lambda n: -found[n])[:ISLAND_MAX_NAMES] for c, found in names.items()}


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
    island = [c for c, g in clusters if (g.region == "Montréal").mean() >= 0.6]
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


def report(df: pd.DataFrame, gas_type: str) -> pd.DataFrame:
    """Summarizes quality metrics for each cluster.

    Parameters
    ----------
    df : pandas.DataFrame
        Clustered station data.
    gas_type : str
        Price column to summarize.

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


def fit_target(df, gas_type, p: Params, target_k: int):
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

    Returns
    -------
    tuple
        Best clustered data, achieved cluster count, and Ward threshold.
    """
    import copy
    lo, hi = 1.0, 5000.0
    best = None
    for _ in range(18):
        mid = (lo * hi) ** 0.5
        q = copy.copy(p); q.threshold = mid
        d = fit(df, gas_type, q)
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
