"""
Exploratory analysis of the price history: what do stations' prices do over a day, and what makes them move together?

Usage (from the repository root)::

    uv run python design/history/clustering/export_history.py   # once, or after new data arrives
    uv run python design/history/clustering/analysis.py

Reads the CSV files in ``data/`` (made by ``export_history.py``) and writes the report to ``output/analysis_report.md`` and the figures
to ``output/*.png``. Each numbered section answers one question; README.md in this folder explains the reasoning.
"""
from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")  # Figures are written to files, never shown.
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE: Path = Path(__file__).parent
DATA_DIR: Path = HERE / "data"
OUT_DIR: Path = HERE / "output"
GAS_TYPE: str = "Régulier"
LOCAL_TZ: ZoneInfo = ZoneInfo("America/Toronto")
LAT0: float = 45.5  # Same projection origin as scripts/clustering.py.
JUMP_CENTS: float = 8.0  # A rise this large in one run counts as a price-cycle "jump".
CELL_KM: float = 5.0  # Side of the grid cell used to represent "area" in the variance comparison.
DISTANCE_BINS: list[float] = [0, 1, 2, 4, 8, 16, 40, 200]

# The report is printed and also kept, so the numbers can be read without running anything.
_report: list[str] = []
TIME_FORMAT: str = "%m/%d %H:%M"  # Tick labels for local time, e.g. 11/16 00:30.


def style_axes(ax: plt.Axes, time_axis: bool = False) -> None:
    """
    Adds light gridlines to an axes and, for time axes, formats the ticks as MM/DD HH:mm.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Axes to style.
    time_axis : bool, default=False
        Whether the x-axis holds timestamps.
    """
    ax.grid(True, which="major", color="#b0b0b0", linestyle=":", linewidth=0.6)
    ax.set_axisbelow(True)  # Gridlines sit behind the lines and bars.
    if time_axis:
        # Matplotlib displays dates in UTC unless told otherwise, so the local zone is passed explicitly.
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=LOCAL_TZ))
        ax.xaxis.set_major_formatter(mdates.DateFormatter(TIME_FORMAT, tz=LOCAL_TZ))


def say(text: str = "") -> None:
    """
    Prints a line and keeps it for the saved report.

    Parameters
    ----------
    text : str, default=""
        Line to print.
    """
    print(text)
    _report.append(text)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Loads the exported tables and projects station coordinates to kilometres.

    Returns
    -------
    stations : pandas.DataFrame
        One row per station, indexed by station id, with ``x_km`` and ``y_km``.
    runs : pandas.DataFrame
        One row per fetch, with the UTC timestamp and the local-time label.
    changes : pandas.DataFrame
        Every stored price change.
    """
    stations = pd.read_csv(DATA_DIR / "stations.csv").set_index("id")
    # Some stations have no brand in the feed; a label keeps them in the brand comparison instead of breaking the grouping.
    stations["brand"] = stations.brand.fillna("Unknown")
    runs = pd.read_csv(DATA_DIR / "runs.csv", parse_dates=["fetched_at"])
    changes = pd.read_csv(DATA_DIR / "price_changes.csv")

    # Same projection as the clustering code, so distances here match the ones the clusters use.
    stations["x_km"] = (stations.lon + 73.6) * 111.32 * np.cos(np.radians(LAT0))
    stations["y_km"] = (stations.lat - LAT0) * 110.57

    runs["local"] = runs.fetched_at.dt.tz_convert(LOCAL_TZ)
    return stations, runs, changes


def price_matrix(stations: pd.DataFrame, runs: pd.DataFrame, changes: pd.DataFrame, gas_type: str) -> pd.DataFrame:
    """
    Rebuilds every station's price at each run from the stored changes.

    A price stays in force until the next change, so gaps between changes are forward filled. Stations without a price
    for the whole window (joined the feed late) are dropped.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations indexed by id.
    runs : pandas.DataFrame
        Fetch times, in order.
    changes : pandas.DataFrame
        Stored price changes.
    gas_type : str
        Fuel to rebuild.

    Returns
    -------
    pandas.DataFrame
        Prices in cents, one row per station and one column per run (local time stamps).
    """
    sub = changes[changes.gas_type == gas_type].copy()
    sub["observed_at"] = pd.to_datetime(sub.observed_at, utc=True)
    wide = sub.pivot(index="station_id", columns="observed_at", values="price")
    wide = wide.reindex(index=stations.index, columns=runs.fetched_at).ffill(axis=1)
    wide.columns = runs.local
    # Stations that joined the feed mid-window have no earlier price; the clustering needs full series, so they are left out.
    return wide.dropna(how="any")


# ======================================================================================
# 1. Coverage: is there enough clean data to say anything?
# ======================================================================================
def section_coverage(stations: pd.DataFrame, runs: pd.DataFrame, changes: pd.DataFrame) -> None:
    """
    Reports how much data there is and how often prices change.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations indexed by id.
    runs : pandas.DataFrame
        Fetch times.
    changes : pandas.DataFrame
        Stored price changes.
    """
    say("## 1. Coverage\n")
    gaps = runs.fetched_at.diff().dropna().dt.total_seconds() / 60
    span_h = (runs.fetched_at.iloc[-1] - runs.fetched_at.iloc[0]).total_seconds() / 3600
    say(f"- Runs: {len(runs)}, {runs.local.iloc[0]:%a %H:%M} to {runs.local.iloc[-1]:%a %H:%M} local ({span_h:.0f} h).")
    say(f"- Gap between runs: median {gaps.median():.1f} min, max {gaps.max():.1f} min, {(gaps > 45).sum()} gaps over 45 min.")
    say(f"- Stations: {len(stations)}; left the feed before the last run: {(stations.last_seen != stations.last_seen.max()).sum()}.")
    say("- Stations per region: " + ", ".join(f"{r} {n}" for r, n in stations.region.value_counts().items()) + ".")
    say("- Stations per brand: " + ", ".join(f"{b} {n}" for b, n in stations.brand.value_counts().head(8).items()) + ".")

    # The first run stores every station's price, so only later rows are genuine changes.
    first_run = changes.observed_at.min()
    later = changes[changes.observed_at != first_run]
    say("")
    say("| Fuel | Changes after run 1 | Stations that changed | Median changes per changer |")
    say("|---|---|---|---|")
    for gas, grp in later.groupby("gas_type"):
        per_station = grp.groupby("station_id").size()
        say(f"| {gas} | {len(grp)} | {len(per_station)} | {per_station.median():.0f} |")
    say("")
    say("`observed_at` is the fetch time, so timing resolution is one run (30 min).\n")


# ======================================================================================
# 2. The daily cycle: what does the average station do over a day?
# ======================================================================================
def section_cycle(stations: pd.DataFrame, prices: pd.DataFrame, changes: pd.DataFrame, runs: pd.DataFrame) -> None:
    """
    Describes the market-wide price cycle and how regions differ, and draws the figure.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations indexed by id.
    prices : pandas.DataFrame
        Price matrix from `price_matrix`.
    changes : pandas.DataFrame
        Stored price changes.
    runs : pandas.DataFrame
        Fetch times.
    """
    say("## 2. The daily cycle\n")
    market = prices.median()

    # --- Market median ------------------------------------------------------------------
    say("Market median (all mapped stations), every 3 hours:\n")
    say("| Local time | Median ¢ | 10th pct | 90th pct |")
    say("|---|---|---|---|")
    for col in prices.columns[::6]:
        say(f"| {col:%a %H:%M} | {market[col]:.1f} | {prices[col].quantile(.1):.1f} | {prices[col].quantile(.9):.1f} |")

    # --- When do changes and jumps happen ---------------------------------------------
    steps = prices.diff(axis=1).iloc[:, 1:]
    jumps = (steps >= JUMP_CENTS).sum()
    big = jumps[jumps >= 5]
    say("")
    say(f"Rises of {JUMP_CENTS:.0f}¢ or more, per run (runs with 5+): " + ", ".join(f"{c:%a %H:%M} {n}" for c, n in big.items()) + ".")
    changed = (steps != 0).sum()
    busiest = changed.nlargest(1)
    say(f"Busiest run for any change: {busiest.index[0]:%a %H:%M} with {busiest.iloc[0]} stations changing.")
    flat = (prices.max(axis=1) == prices.min(axis=1)).sum()
    say(f"Stations whose price never changed in the window: {flat}.")
    moved = steps[steps != 0].stack()
    say(f"Step sizes (¢): 1st pct {moved.quantile(.01):.0f}, 5th {moved.quantile(.05):.0f}, median {moved.median():.0f}, "
        f"95th {moved.quantile(.95):.0f}, 99th {moved.quantile(.99):.0f}.\n")

    # --- Regions react differently ----------------------------------------------------
    say("Regional mean price relative to the start (¢), every 4.5 hours:\n")
    cols = prices.columns[::9]
    say("| Region | " + " | ".join(f"{c:%a %H:%M}" for c in cols) + " |")
    say("|---|" + "---|" * len(cols))
    regional = {}
    for region, ids in stations.groupby("region").groups.items():
        series = prices.loc[ids].mean()
        regional[region] = series - series.iloc[0]
        say(f"| {region} | " + " | ".join(f"{regional[region][c]:+.1f}" for c in cols) + " |")
    say("")

    # --- Figure -------------------------------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    for region, series in regional.items():
        axes[0].plot(series.index, series.values, label=region)
    axes[0].set(ylabel="Mean price change since first run (¢)", title="Régulier: one price cycle, different amplitude per region")
    axes[0].legend(ncols=3, fontsize=8)
    axes[1].bar(jumps.index, jumps.values, width=0.015, color="#c0392b")
    axes[1].set(ylabel=f"Stations rising ≥{JUMP_CENTS:.0f}¢", xlabel="Local time (MM/DD HH:mm)")
    for ax in axes:
        style_axes(ax, time_axis=True)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "cycle.png", dpi=130)
    plt.close(fig)


# ======================================================================================
# 3. Premium structure: how much of a station's behaviour is level, and how much is movement?
# ======================================================================================
def premium_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Subtracts the market median at each run, leaving each station's premium over the market.

    Parameters
    ----------
    prices : pandas.DataFrame
        Price matrix from `price_matrix`.

    Returns
    -------
    pandas.DataFrame
        Premium in cents, same shape as `prices`.
    """
    return prices.sub(prices.median(), axis=1)


def section_structure(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Separates each station's persistent price level from its movement, and finds the dominant movement patterns.

    Parameters
    ----------
    prices : pandas.DataFrame
        Price matrix from `price_matrix`.

    Returns
    -------
    pandas.DataFrame
        Demeaned premium (movement only), one row per station.
    """
    say("## 3. Level versus movement\n")
    premium = premium_matrix(prices)
    level = premium.mean(axis=1)
    wobble = premium.std(axis=1)
    say(f"- Spread of stations' average premium (level): std {level.std():.1f}¢.")
    say(f"- Typical temporal wobble of a station's premium: mean std {wobble.mean():.1f}¢ (10th-90th pct {wobble.quantile(.1):.1f}"
        f"-{wobble.quantile(.9):.1f}¢).")

    # --- Principal components of the movement ----------------------------------------
    # Removing each station's level first means the components describe how stations move, not where they sit.
    movement = premium.sub(level, axis=0)
    _, singular, vt = np.linalg.svd(movement.to_numpy(), full_matrices=False)
    explained = singular**2 / np.sum(singular**2)
    say(f"- Share of movement variance explained by principal components 1-5: {', '.join(f'{e:.0%}' for e in explained[:5])}.")
    say("  The first two components are a handful of numbers that describe most stations, so the dynamics are low-dimensional.\n")

    fig, ax = plt.subplots(figsize=(9, 3.8))
    for k in range(2):
        curve = vt[k] * singular[k] / np.sqrt(len(movement))
        ax.plot(prices.columns, curve, label=f"PC{k + 1} ({explained[k]:.0%} of movement)")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set(ylabel="Typical effect on premium (¢)", xlabel="Local time (MM/DD HH:mm)", title="The two dominant movement patterns")
    style_axes(ax, time_axis=True)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "components.png", dpi=130)
    plt.close(fig)
    return movement


# ======================================================================================
# 4. Who moves with whom: distance, brand, or area?
# ======================================================================================
def pair_table(stations: pd.DataFrame, movement: pd.DataFrame) -> pd.DataFrame:
    """
    Builds one row per station pair with its distance, brand match and trajectory correlation.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations indexed by id, with projected coordinates.
    movement : pandas.DataFrame
        Demeaned premium per station and run.

    Returns
    -------
    pandas.DataFrame
        Columns ``dist_km``, ``same_brand``, ``same_region`` and ``corr``.
    """
    xy = stations.loc[movement.index, ["x_km", "y_km"]].to_numpy()
    dist = np.hypot(xy[:, [0]] - xy[:, 0][None], xy[:, [1]] - xy[:, 1][None])
    brand = stations.loc[movement.index, "brand"].to_numpy()

    # Pearson correlation of every pair of trajectories; flat trajectories have no defined correlation and drop out.
    centred = movement.to_numpy() - movement.to_numpy().mean(axis=1, keepdims=True)
    norm = np.linalg.norm(centred, axis=1)
    norm[norm == 0] = np.nan
    corr = (centred @ centred.T) / norm[:, None] / norm[None]

    upper = np.triu_indices(len(movement), k=1)
    region = stations.loc[movement.index, "region"].to_numpy()
    pairs = pd.DataFrame({
        "dist_km": dist[upper],
        "same_brand": (brand[:, None] == brand[None])[upper],
        "same_region": (region[:, None] == region[None])[upper],
        "corr": corr[upper],
    })
    return pairs.dropna()


def adjusted_r2(feature: np.ndarray, groups: np.ndarray) -> float:
    """
    Calculates how much of a feature's variance a grouping explains, corrected for the number of groups.

    The correction matters because many small groups (such as map cells) would otherwise explain variance by chance.

    Parameters
    ----------
    feature : numpy.ndarray
        One value per station.
    groups : numpy.ndarray
        Group label per station.

    Returns
    -------
    float
        Adjusted R-squared; 0 means no better than chance.
    """
    series = pd.Series(feature)
    within = series.groupby(groups).transform(lambda s: s - s.mean()).pow(2).sum()
    total = ((series - series.mean()) ** 2).sum()
    n, k = len(series), len(np.unique(groups))
    return 1 - (within / (n - k)) / (total / (n - 1))


def section_who_moves_with_whom(stations: pd.DataFrame, prices: pd.DataFrame, movement: pd.DataFrame) -> None:
    """
    Tests whether co-movement follows distance, brand or area, and draws the correlation-versus-distance figure.

    Parameters
    ----------
    stations : pandas.DataFrame
        Stations indexed by id, with projected coordinates.
    prices : pandas.DataFrame
        Price matrix from `price_matrix`.
    movement : pandas.DataFrame
        Demeaned premium per station and run.
    """
    say("## 4. Who moves with whom\n")
    pairs = pair_table(stations, movement)
    pairs["bin"] = pd.cut(pairs.dist_km, DISTANCE_BINS, right=False)

    say("Mean correlation of two stations' movement, by the distance between them:\n")
    say("| Distance (km) | Pairs | All | Same brand | Different brand |")
    say("|---|---|---|---|---|")
    table = pairs.groupby("bin", observed=True).apply(
        lambda g: pd.Series({"n": len(g), "all": g["corr"].mean(), "same": g.loc[g.same_brand, "corr"].mean(),
                             "diff": g.loc[~g.same_brand, "corr"].mean()}),
        include_groups=False,
    )
    for interval, row in table.iterrows():
        say(f"| {interval.left:g}-{interval.right:g} | {row.n:.0f} | {row['all']:.2f} | {row.same:.2f} | {row['diff']:.2f} |")
    say("")
    # Correlation climbs again beyond 40 km. Splitting by region shows it is not only "same region", so it is reported, not explained.
    far = pairs[pairs.dist_km >= 40]
    say(f"Beyond 40 km the correlation rises again. Of those pairs, same-region pairs average "
        f"{far.loc[far.same_region, 'corr'].mean():.2f} and different-region pairs {far.loc[~far.same_region, 'corr'].mean():.2f}. "
        f"Region only partly explains it, and the cause is not established "
        "(possibly a province-wide pattern shared by distant areas). It does not matter for contiguous clusters, which only use "
        "neighbours within a few km.\n")

    # --- Is a station's behaviour better predicted by its area or by its brand? -------
    premium = premium_matrix(prices)
    after_jump = prices.columns[prices.columns.get_indexer([c for c in prices.columns if c.hour == 0 and c.minute >= 20][:1])[0]:]
    features = {
        "Average premium (level)": premium.mean(axis=1),
        "Premium volatility": premium.std(axis=1),
        "Decay rate after the midnight jump (¢/h)": prices[after_jump].apply(
            lambda row: np.polyfit(np.arange(len(row)) / 2, row.to_numpy(), 1)[0], axis=1),
        "Size of the midnight jump (¢)": prices[after_jump[:4]].mean(axis=1) - prices.iloc[:, 8:12].mean(axis=1),
    }
    info = stations.loc[prices.index]
    cell = (info.x_km // CELL_KM).astype(int).astype(str) + "_" + (info.y_km // CELL_KM).astype(int).astype(str)
    say(f"Share of the variation between stations explained by each grouping (adjusted R², {CELL_KM:g} km grid cells for area):\n")
    say("| Feature | Brand | Area (grid cell) | Region |")
    say("|---|---|---|---|")
    for name, values in features.items():
        r2 = [adjusted_r2(values.to_numpy(), info[col].to_numpy() if col != "cell" else cell.to_numpy())
              for col in ("brand", "cell", "region")]
        say(f"| {name} | {r2[0]:.2f} | {r2[1]:.2f} | {r2[2]:.2f} |")

    # --- Does a station look like its six nearest neighbours? --------------------------
    xy = info[["x_km", "y_km"]].to_numpy()
    dist = np.hypot(xy[:, [0]] - xy[:, 0][None], xy[:, [1]] - xy[:, 1][None])
    nearest = np.argsort(dist, axis=1)[:, 1:7]
    say("")
    say("Correlation between a station's value and the mean of its six nearest neighbours: " + ", ".join(
        f"{name.split(' (')[0].lower()} {np.corrcoef(v.to_numpy(), v.to_numpy()[nearest].mean(axis=1))[0, 1]:.2f}"
        for name, v in features.items()) + ".\n")

    # --- Figure -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(range(len(table)), table["same"], "o-", label="Same brand")
    ax.plot(range(len(table)), table["diff"], "s-", label="Different brand")
    ax.set_xticks(range(len(table)), [f"{i.left:g}-{i.right:g}" for i in table.index])
    ax.set(xlabel="Distance between stations (km)", ylabel="Mean correlation of movement", title="Neighbours move together; brand adds little")
    style_axes(ax)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "correlation_vs_distance.png", dpi=130)
    plt.close(fig)


def main() -> None:
    """
    Runs every section, then saves the report and the price matrix.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(exist_ok=True)
    stations, runs, changes = load()
    prices = price_matrix(stations, runs, changes, GAS_TYPE)

    say(f"# Analysis report ({GAS_TYPE})\n")
    section_coverage(stations, runs, changes)
    stations = stations.loc[prices.index]
    section_cycle(stations, prices, changes, runs)
    movement = section_structure(prices)
    section_who_moves_with_whom(stations, prices, movement)

    (OUT_DIR / "analysis_report.md").write_text("\n".join(_report) + "\n", encoding="utf-8")
    prices.round(1).to_csv(DATA_DIR / "prices_regulier.csv")


if __name__ == "__main__":
    main()
