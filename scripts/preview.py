"""Previews station clusters on a Folium map opened in the default browser.

Usage
-----
python -m scripts.preview [stations.geojson] [--gas Régulier] [--clusters 19] [--no-open]

Run from the repository root. Each cluster is its own toggleable layer coloured distinctly; hover a
station for details. Prints a per-cluster quality table to the console. The HTML is written to the
system temporary directory, not `build/`, so it is never deployed.
"""
import argparse
import html
import tempfile
import webbrowser
from pathlib import Path

import folium
import pandas as pd

import scripts.clustering as C
from interactive_map import BaseMapRenderer, MapData

# Distinct colours for adjacent clusters (the matplotlib "tab20" palette).
PALETTE: list[str] = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5", "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
]
UNCLUSTERED_COLOR = "#9e9e9e"


class ClusterMapRenderer(BaseMapRenderer):
    """Renders clustered stations on a Folium map, one coloured layer per cluster."""

    PAGE_TITLE = "Cluster preview"

    def __init__(self, stations: pd.DataFrame, names: dict[int, str], gas_type: str, filename: str = "clusters.html"):
        """
        Parameters
        ----------
        stations : pandas.DataFrame
            Clustered station data with `lat`, `lon`, `cluster` and price columns.
        names : dict[int, str]
            Mapping from cluster identifier to display name.
        gas_type : str
            Price column shown in tooltips and used for the cluster medians.
        filename : str, default="clusters.html"
            Output file name.
        """
        super().__init__(stations, filename)
        self.names = names
        self.gas_type = gas_type

    def _tooltip(self, row: pd.Series) -> str:
        """Builds the hover tooltip HTML for one station.

        Parameters
        ----------
        row : pandas.Series
            Station row.

        Returns
        -------
        str
            Escaped HTML tooltip.
        """
        cluster = self.names.get(row.cluster, "unclustered")
        # The feed leaves some text fields empty (NaN), so coerce them before escaping.
        address = " ".join(str(row.address).split()) if pd.notna(row.address) else ""
        brand = row.brand if pd.notna(row.brand) else "no brand"
        return (
            f"<b>{html.escape(' '.join(str(row['name']).split()))}</b> ({html.escape(str(brand))})<br>"
            f"{html.escape(address)}<br>{row[self.gas_type]:.1f}¢ · {html.escape(cluster)}"
        )

    def _add_cluster_layers(self) -> None:
        """Adds one marker layer per cluster, plus an unclustered layer."""
        s = self.stations
        for cluster, group in [(-1, s[s.cluster < 0])] + list(s[s.cluster >= 0].groupby("cluster")):
            if group.empty:
                continue
            color = UNCLUSTERED_COLOR if cluster < 0 else PALETTE[cluster % len(PALETTE)]
            label = "Unclustered" if cluster < 0 else self.names[cluster]
            layer = folium.FeatureGroup(name=f"{label} (n={len(group)})")

            # --- Station markers -----------------------------------------------------
            for _, row in group.iterrows():
                folium.CircleMarker(
                    location=(row.lat, row.lon), radius=4 if cluster < 0 else 6, color="#000000", weight=0.6,
                    fill=True, fill_color=color, fill_opacity=0.85, tooltip=self._tooltip(row),
                ).add_to(layer)

            # --- Cluster name label at the centroid ----------------------------------
            if cluster >= 0:
                folium.Marker(
                    location=(group.lat.mean(), group.lon.mean()),
                    icon=folium.DivIcon(
                        icon_size=(0, 0), icon_anchor=(0, 0), class_name="cluster-label",
                        html=f'<div class="cluster-label-text">{html.escape(label)}</div>',
                    ),
                    interactive=False,
                ).add_to(layer)
            layer.add_to(self.inter_map)

    def _add_legend(self, report: pd.DataFrame) -> None:
        """Adds a colour legend panel and the label styling.

        Parameters
        ----------
        report : pandas.DataFrame
            Per-cluster quality table indexed by cluster identifier.
        """
        rows = "".join(
            f'<div><span class="sw" style="background:{PALETTE[c % len(PALETTE)]}"></span>'
            f"{html.escape(self.names[c])} · {r['median']:.0f}¢ · n={r.n}</div>"
            for c, r in report.sort_values(["region", "median"]).iterrows()
        )
        legend = f"""
        <style>
            .cluster-legend {{
                position: fixed; top: 10px; left: 55px; z-index: 9999; max-height: 70vh; overflow-y: auto;
                background: rgba(255,255,255,0.9); border-radius: 8px; padding: 8px 12px;
                font: 11px/1.7 sans-serif; box-shadow: 0 2px 8px rgba(0,0,0,0.18);
            }}
            .cluster-legend .sw {{
                display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                border: 1px solid #000; margin-right: 6px;
            }}
            .cluster-label {{ background: none !important; border: none !important; }}
            .cluster-label-text {{
                transform: translate(-50%, -50%); white-space: nowrap; font: bold 11px sans-serif;
                background: rgba(255,255,255,0.75); padding: 0 3px; border-radius: 3px;
            }}
        </style>
        <div class="cluster-legend">{rows}</div>
        """
        self.inter_map.get_root().html.add_child(folium.Element(legend))

    def render(self, report: pd.DataFrame) -> Path:
        """Renders the cluster map and saves it to the temporary directory.

        Parameters
        ----------
        report : pandas.DataFrame
            Per-cluster quality table from `clustering.report`.

        Returns
        -------
        pathlib.Path
            Path of the saved HTML file.
        """
        # tiles=None because the CartoDB basemap is added by the shared base class
        self.inter_map = folium.Map(location=(self.stations.lat.median(), self.stations.lon.median()), zoom_start=9, tiles=None)
        self._add_cluster_layers()
        self._add_tile_layer()
        self._add_info()
        self._update_popover_styles()
        self._add_legend(report)
        return self._save(Path(tempfile.gettempdir()) / "essence_clusters")


def main() -> Path:
    """Runs the station-cluster preview CLI.

    Returns
    -------
    pathlib.Path
        Path of the generated HTML map.

    Raises
    ------
    ValueError
        If the station feed cannot be fetched after the retry limit.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("geojson", nargs="?", help="local GeoJSON path (defaults to the station feed)")
    ap.add_argument("--gas", default="Régulier")
    ap.add_argument("--clusters", type=int, default=19, help="target number of clusters")
    ap.add_argument("--no-open", action="store_true", help="write the HTML without opening the browser")
    a = ap.parse_args()

    # --- Load stations -----------------------------------------------------------------
    if a.geojson is None:
        map_data = MapData()
        map_data.fetch_data()
        stations = C.load_stations_data(map_data.data, a.gas)
    else:
        stations = C.load_stations(a.geojson, a.gas)

    # --- Cluster and report ------------------------------------------------------------
    df, k, thr = C.fit_target(stations, a.gas, C.Params(), a.clusters)
    names = C.label_clusters(df)
    rep = C.report(df, a.gas)
    rep["name"] = rep.index.map(names)
    print(f"{k} clusters (Ward threshold {thr:.0f}), {(df.cluster < 0).sum()} of {len(df)} stations unclustered")
    print(rep.sort_values(["region", "median"]).to_string())

    # --- Render and open ---------------------------------------------------------------
    path = ClusterMapRenderer(df, names, a.gas).render(rep)
    print(f"Cluster map saved to {path}")
    if not a.no_open:
        webbrowser.open(path.as_uri())
    return path


if __name__ == "__main__":
    main()
