# Gas Price History: Plan

_Status: draft 9, 2026-11-15. Iterating._

> **Keep this plan current.** Update it whenever a decision is confirmed, something is implemented, or an open question is resolved or added, and add a changelog line with the date. Do it in the same turn as the change, not later.

## Goal

Add price history to the Quebec Gas Price Map.

- **Phase 1:** line charts of the average (median) price per area over the last 3-7 days.
- **Phase 2:** a time slider on the existing interactive map that shows prices at the selected time.

## Decisions so far (confirmed by you)

- The script keeps running on the Raspberry Pi 3B+ (32 GB SD card) every 30 minutes (more reliable than GitHub Actions).
- No Supabase or other hosted database. History is stored locally and the site stays static (precomputed files published with the HTML).
- Only price *changes* are stored, not 30-minute snapshots.
- History window: at least 3 days, ideally 7.
- Clusters are **large** and **data-driven** (geography + price similarity), not hardcoded. Reason: nearby areas can differ a lot (e.g. Sainte-Thérèse is much cheaper than Sainte-Marthe-sur-le-Lac).
- **Minimum cluster size: 12 stations** (12+ is "big enough").
- **Rural stations** that are too few or too far from a cluster stay **unclustered**; no statistics are computed for them.
- Clusters must be stable over time and free of heavy outliers.
- Phase 1 shows a line graph of the average price per cluster.
- Phase 2 reuses the current interactive map and adjusts the data by slider time.

## What the snapshot told us (stations.geojson, 2026-11-14)

- 2,473 stations province-wide; **961** are in the regions your map shows (Montérégie 387, Montréal 226, Laurentides 190, Lanaudière 87, Laval 71). 14 province-wide have no Régulier price.
- **No station ID and no per-price timestamp** in the feed. Name + coordinates (5 decimals) is unique (0 duplicates), so it works as the station key. Caveat: if a station is renamed or its coordinates are corrected, it looks like a new station; the module should match on coordinates first.
- Messy text: city names vary in case and abbreviation (`SAINTE-...`, `St-Jean-sur-Richelieu`) and some names contain `\r\n`. Both need normalising.
- Sainte-Thérèse stations sell Régulier at ~154-159¢; Sainte-Marthe-sur-le-Lac at ~165-173¢. The clustering separates them.
- Within a cluster, stations still differ by ~2-5¢ (IQR), and some are 25-45¢ above the local median (e.g. 191.9¢ and 196.9¢ in Saint-Jean-sur-Richelieu). Medians are therefore the right statistic, not means.

## Clustering design (prototype in `clustering.py`)

- **Region constraint:** stations only connect to others in the same feed `Region`, except regions joined by land (currently Laurentides + Lanaudière, the North Shore), which may share clusters. Montréal, Laval and Montérégie are separated by rivers. An unrestricted run merged the east end of the island with Terrebonne, which is why the exception list is explicit (`linked_regions`).
- **Size cap:** clusters of more than 75 stations are re-split into contiguous pieces (Ward), so dense urban areas get finer clusters while sparse areas can stay geographically large. This splits the Montréal island into 4 clusters without any hardcoded boundaries.
- **Island naming:** clusters made mostly of Montréal-region stations get local area names ("Montréal (West Island)", "Centre-Ouest", "Sud-Ouest", "Centre-Ville", "Nord", "Est"). Each cluster is matched one-to-one (Hungarian assignment) to the nearest of a few named reference points (`ISLAND_ANCHORS` in `clustering.py`), so primary names are unique and follow Montréal usage rather than compass directions. A cluster whose stations are at least 25% nearest to a second reference point takes that name too, most common first, max two (e.g. "Montréal (Nord / Centre-Ville)"). Compass names remain only as a fallback if there are more island clusters than anchors.
- **Data quality:** the feed contains a station at coordinates (0, 0) ("Hub Régie", Montréal), which passes the region filter. It is now dropped by a coordinate sanity check.
- **Connectivity graph:** 6 nearest neighbours per station, edges longer than **10 km dropped**. Connected groups of fewer than 12 stations become unclustered (60 of 961 in the prototype).
- **Features:** `(x_km, y_km, 5 × smoothed premium)`. Premium = price minus the regional median, clipped to ±15¢ and smoothed with the median of the 7 nearest stations. This keeps single outlier stations from steering the clusters.
- **Algorithm:** Ward agglomerative clustering restricted to the graph (clusters stay contiguous). The Ward threshold is bisected to give about 18 clusters. Clusters under 12 stations merge into their nearest neighbouring cluster.
- **Region bounds:** `REGIONS` in `scripts/interactive_map.py` is the single source of truth for which stations are mapped and clustered; `clustering.py` imports it.
- **Labels:** non-island clusters are named after their most common municipalities, keeping only those with at least **20%** of the cluster's stations (max 2; the top one is always kept). A cluster of 30 stations in Saint-Jean-sur-Richelieu plus one or two elsewhere is just "Saint-Jean-sur-Richelieu". `cluster_names.json` overrides are planned.
- **Freeze:** the station-to-cluster assignment is saved and versioned; new stations join the cluster of their nearest neighbours; re-fit manually or when a cluster's spread degrades.

### First result (18 clusters, 899 stations clustered, 60 unclustered)

| Area | Clusters | Notes |
|---|---|---|
| Montréal island | 3 (61 / 54 / 110 stations) | Prices are fairly uniform, so the split is mostly geographic. One cluster of 110 covers the West Island plus the south-west. |
| Laval | 1 (71) | Very tight (IQR 2¢). |
| Longueuil/Brossard | 1 (59, median 150¢) | Clearly cheaper than the island, as you observed. |
| Châteauguay/Brossard, Boucherville/Saint-Bruno | 2 | |
| Suroît + Vaudreuil-Soulanges | 1 (61) | Merged by the algorithm; they could be split with a higher price weight. |
| Saint-Jean-sur-Richelieu | 1 (40) | Bimodal (147-157¢ vs 166-170¢), IQR 18¢. |
| Laurentides / Lanaudière | 5 | Sainte-Thérèse sits in a different cluster from Sainte-Marthe-sur-le-Lac. |

### Known limitations of the prototype

- A single snapshot cannot show whether stations in a cluster **move together over time**. That is the property the charts need, so we must re-check the clusters after a few days of history.
- A few clusters are geographically wide (up to 40-65 km, e.g. Saint-Hyacinthe/Beloeil, Saint-Jérôme/Sainte-Agathe). A maximum diameter cap would split them.
- The Montréal island has no separate "Downtown" cluster: the price differences there are too small for the algorithm to pick up.

## Storage (implemented in `scripts/history.py`, draft 9)

- SQLite file on the Pi (WAL mode, daily `.backup`). About 10 days of retention, keeping the last price before the cutoff for each station.
- Tables:
  - `runs(run_id, fetched_at)`, one row per successful fetch
  - `stations(id, key, name, brand, address, lat, lon, cluster, first_seen, last_seen)`
  - `price_changes(station_id, gas_type, price, observed_at)`, inserted only when the price differs from the last stored value
- Size estimate: a few MB per day, far below the SD card capacity.
- As built: DB at `data/history.sqlite` (override with `ESSENCE_DB`, git-ignored); 10-day retention keeping the boundary price; a NULL price records a fuel no longer sold; only `REGIONS`-filtered stations are stored; renamed stations are matched by coordinates; daily backups (last 7) in `data/backups/`. The preview build (development branch) runs with `--no-history` so each fetch is recorded once. A history failure never blocks the map build (non-zero exit only).

## Chart values

- Cluster value = median with an IQR band. Price at time T = latest change at or before T. Hourly points.
- One cluster set (fitted on Régulier) for all three fuels.

## Outputs (static, next to `index.html`)

- `history.json`: per cluster, with id, name, outline (hull), station count, and a time series per fuel (Phase 1).
- Per-station change lists for the Phase 2 slider; the browser computes the price at time T by binary search.

## Pipeline (per run)

1. Fetch + parse + filter regions (`main.py`, one fetch shared by everything)
2. Record the run and price changes in SQLite (done)
3. Assign stations to the frozen clusters
4. Compute cluster series and export JSON
5. Render the three maps (existing code) and deploy

## Resolved in draft 4

- Suroît + Vaudreuil-Soulanges stay merged (the data put them together).
- Clusters may cross the Region boundary where land-connected (see above).
- Large clusters are fine for distant areas (Saint-Jérôme, Saint-Hyacinthe); only dense areas are split, via the size cap.
- Montréal island: 4 data-driven clusters, geographic names.

## Open questions

1. ~~Island cluster names~~ resolved in draft 6: local names via reference points. A `cluster_names.json` override is still possible if you want finer control.
5. **Bimodal clusters** (Saint-Jean-sur-Richelieu): accept the wide IQR band, or split by price level?
6. **Chart UI:** where does it open (click a cluster outline, a station tooltip link, a panel)? It must not clash with the footer and recenter button on mobile.
7. **Phase 2 colour scale:** fixed across time or rescaled per time step?

## Build order

1. ~~Prototype the clustering on a snapshot~~ (done: `clustering.py` + `preview.py`, a developer-only Folium map opened in the browser for vetting clusters, built on `BaseMapRenderer` from `interactive_map.py`; end users never see the clusters themselves, only the charts)
2. ~~`history.py`: SQLite store (record run, change detection, retention)~~ (done: `scripts/history.py`, wired into `main.py`)
3. Cluster freezing/assignment + quality report, integrated into `main.py`
4. Export `history.json` and add the chart panel
5. Phase 2: export per-station changes and add the slider

## Changelog

- 2026-11-15: draft 9. History store implemented (`scripts/history.py`). `interactive_map.py` split into `main.py` (entry point, single fetch) and `scripts/interactive_map.py` (map code, `REGIONS`). GitHub Actions workflow removed; the Pi (cron -> `assets/deploy-page`) is the only builder. README documents the topology and Pi setup.
- 2026-11-15: draft 8. Island naming: added a Centre-Ville reference point (replacing "Centre", which was never a primary name in the snapshot and overlapped it). Clusters now carry a second area name when 25%+ of their island stations are nearest to it, e.g. "Montréal (Nord / Centre-Ville)". At 25 clusters the island splits out a standalone Centre-Ville cluster.
- 2026-11-15: draft 7. `preview.py` now renders a Folium map (one toggleable coloured layer per cluster, legend, hover tooltips) opened in the browser, replacing the matplotlib window. `interactive_map.py` gained `BaseMapRenderer` (shared page chrome) and a `__main__` guard, and now owns `REGIONS` for both the map and the clustering. Municipality names under 20% of a cluster are dropped from its name. README documents the clustering. Added the "keep this plan current" rule.
- 2026-11-15: draft 6. Island clusters now use Montréal-style names (West Island, Centre-Ouest, Sud-Ouest, Centre, Nord, Est) via nearest-reference-point matching. At the default 19-cluster target the island has 6 clusters.
- 2026-11-14: draft 5. Cluster vetting is a developer-only tool (`preview.py`, interactive matplotlib window with hover details and a per-cluster quality table). The HTML cluster map idea was dropped. Tuned parameters are now the defaults in `clustering.py`.
- 2026-11-14: draft 4. Size cap and land-linked regions added; island split into 4 clusters with compass names; invalid-coordinate station filtered.
- 2026-11-14: draft 3. Min size 12 and rural-unclustered rule confirmed. Prototype run on the snapshot; findings on station IDs, data quirks and first cluster results added. Open questions updated.
- 2026-11-14: draft 2. Clusters changed from hand-defined to data-driven (frozen after fitting).
- 2026-11-14: draft 1 created.
