# Gas Price History: Plan

_Status: draft 15, 2026-11-19. Phase 1 complete; Phase 2 on hold._

> **Keep this plan current.** Update it whenever a decision is confirmed, something is implemented, or an open question is resolved or added, and add a changelog line with the date. Do it in the same turn as the change, not later.

## Goal

Add price history to the Quebec Gas Price Map.

- **Phase 1:** line charts of the average (median) price per area over the last 3-7 days.
- **Phase 1 (complete, 2026-11-19):** statistics page with line charts of the price per cluster over the last 3-7 days.
- **Phase 2 (on hold):** a time slider on the existing interactive map that shows prices at the selected time.

## Decisions so far (confirmed by you)

- **Phase 1 accepted as built (2026-11-19)**, committed as `88a0bb8`. The chart shows the mean with min and max, not the median with IQR planned earlier (see Chart values). Phase 2 is on hold; no slider work until you restart it.

- The script keeps running on the Raspberry Pi 3B+ (32 GB SD card) every 30 minutes (more reliable than GitHub Actions).
- No Supabase or other hosted database. History is stored locally and the site stays static (precomputed files published with the HTML).
- Only price *changes* are stored, not 30-minute snapshots.
- History window: at least 3 days, ideally 7.
- Clusters are **large** and **data-driven** (geography + price behaviour), not hardcoded. Motivation: nearby areas can differ a lot (the first snapshot showed Sainte-Thérèse much cheaper than Sainte-Marthe-sur-le-Lac). That was an observation, **not a requirement**: if the data say two areas behave alike, they may end up in the same cluster.
- Clusters should group stations that **trend together over a day**, so they are fitted on the **price history**: the hourly premium over the **most recent 3 days, or as much as is available** if less (draft 13; see [clustering/README.md](clustering/README.md)). At 4 days a history fit is no better than the *best* snapshot but matches it every time, whereas a snapshot ranges from worse than geography to equal to the history fit depending on when it was taken (README section 6). Fitting on history removes that dependence, so the 7-day re-run is not needed for this decision.
- **Scope: Régulier only.** Other grades (Super, Diesel) are out of scope for the fit, the charts and the statistics.
- **Minimum cluster size: 12 stations** (12+ is "big enough").
- **Rural stations** that are too few or too far from a cluster stay **unclustered**; no statistics are computed for them.
- Clusters must be stable over time and free of heavy outliers.
- Phase 1 shows a line graph of the average price per cluster.
- Phase 2 reuses the current interactive map and adjusts the data by slider time.

## What the snapshot told us (stations.geojson, 2026-11-14)

- 2,473 stations province-wide; **961** are in the regions your map shows (Montérégie 387, Montréal 226, Laurentides 190, Lanaudière 87, Laval 71). 14 province-wide have no Régulier price.
- **No station ID and no per-price timestamp** in the feed. Name + coordinates (5 decimals) is unique (0 duplicates), so it works as the station key. Caveat: if a station is renamed or its coordinates are corrected, it looks like a new station; the module should match on coordinates first.
- Messy text: city names vary in case and abbreviation (`SAINTE-...`, `St-Jean-sur-Richelieu`) and some names contain `\r\n`. Both need normalising.
- Sainte-Thérèse stations sell Régulier at ~154-159¢; Sainte-Marthe-sur-le-Lac at ~165-173¢. The snapshot clustering separated them; whether a history-based one does is still to be checked.
- Within a cluster, stations still differ by ~2-5¢ (IQR), and some are 25-45¢ above the local median (e.g. 191.9¢ and 196.9¢ in Saint-Jean-sur-Richelieu). Medians are therefore the right statistic, not means.

## Clustering design (prototype in `clustering.py`)

- **Region constraint:** stations only connect to others in the same feed `Region`, except regions joined by land (currently Laurentides + Lanaudière, the North Shore), which may share clusters. Montréal, Laval and Montérégie are separated by rivers. An unrestricted run merged the east end of the island with Terrebonne, which is why the exception list is explicit (`linked_regions`).
- **Size cap:** clusters of more than 75 stations are re-split into contiguous pieces (Ward), so dense urban areas get finer clusters while sparse areas can stay geographically large. This splits the Montréal island into 4 clusters without any hardcoded boundaries.
- **Island naming:** clusters made mostly of Montréal-region stations get local area names ("Montréal (West Island)", "Centre-Ouest", "Sud-Ouest", "Centre-Ville", "Nord", "Est"). Each cluster is matched one-to-one (Hungarian assignment) to the nearest of a few named reference points (`ISLAND_ANCHORS` in `clustering.py`), so primary names are unique and follow Montréal usage rather than compass directions. A cluster whose stations are at least 25% nearest to a second reference point takes that name too, most common first, max two (e.g. "Montréal (Nord / Centre-Ville)"). Compass names remain only as a fallback if there are more island clusters than anchors.
- **Data quality:** the feed contains a station at coordinates (0, 0) ("Hub Régie", Montréal), which passes the region filter. It is now dropped by a coordinate sanity check.
- **Connectivity graph:** 6 nearest neighbours per station, edges longer than **8 km dropped** (`Params.max_edge_km`; this said 10 km before draft 11, which was wrong). Connected groups of fewer than 12 stations become unclustered (60 of 961 in the prototype; 102 in the history experiments at 27 h and 4 days).
- **Features (current, snapshot-based):** `(x_km, y_km, 1.5 × smoothed premium)` (`Params.alpha`; the plan used to say 5 ×). Premium = price minus the overall median of the mapped stations (not per region), clipped to ±15¢ and smoothed with the median of the 7 nearest stations. This keeps single outlier stations from steering the clusters. **To be replaced** by history features (decided in draft 13; see the proposal below).
- **Algorithm:** Ward agglomerative clustering restricted to the graph (clusters stay contiguous). The Ward threshold is bisected to give about 19 clusters (`TARGET_CLUSTERS` in `freeze_clusters.py`; the first prototype used 18). Clusters under 12 stations merge into their nearest neighbouring cluster.
- **Region bounds:** `REGIONS` in `scripts/interactive_map.py` is the single source of truth for which stations are mapped and clustered; `clustering.py` imports it.
- **Labels:** non-island clusters are named after their most common municipalities, keeping only those with at least **20%** of the cluster's stations (max 2; the top one is always kept). A cluster of 30 stations in Saint-Jean-sur-Richelieu plus one or two elsewhere is just "Saint-Jean-sur-Richelieu". `cluster_names.json` overrides are planned.
- **Freeze:** the station-to-cluster assignment is saved in the database (`clusters` table and `stations.cluster`, schema v2); new stations join the cluster of their nearest clustered station within 8 km; re-fit manually (`freeze_clusters --force`) or when a cluster's spread degrades.

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

### What 4 days of history told us (draft 12; 27 h in draft 11)

Full write-up, scripts, data and figures: [clustering/README.md](clustering/README.md). Data: `data/history.sqlite`, 191 runs, 2026-11-15 17:50 to 2026-11-19 17:20 local, 963 stations (961 with a full series; two joined mid-window and are left out of the fit analysis).

- **A day is one price cycle, and it repeats.** 150-240 stations raise their price by 8¢ or more at 00:20 on each of the 4 nights (smaller waves at 22:20-23:20 and 00:50), then prices decline over the day. The market median peaks at 164.9-167.9¢ and falls to 154-159¢. The whole cycle drifts down about 3-5¢ over the 4 days. Regions differ in amplitude (Laval +8.6¢ at the first jump, Laurentides +2.8¢).
- **Level and movement are different.** Station levels differ by 7.6¢ (std); their movement over the window by about 3.8¢. After removing level, the first two components explain 59% of the movement (49% and 10%; 73% at 27 h), so a short trajectory still describes a station, with a bit more variety.
- **Co-movement is geographic.** Movement correlation is 0.63 under 1 km and about 0.10 at 8-16 km; brand adds about 0.1. Area explains 34-58% of station-level features, brand 2-12%.
- **History features do not clearly beat the snapshot.** Fitted on one half of the window and scored on the other (project's own Ward pipeline, about 19 clusters), snapshot (shape R² 0.313), trajectory (0.311), shape-only (0.298) and geography alone (0.299) are within 0.015; only the window-average premium is lower (0.274). Trajectory has the best level R² (0.233) and correlation (0.45) but only by a margin that is within noise. The shape-only edge seen at 27 h is gone. Clusters fitted by different methods agree at an adjusted Rand index of 0.80-0.89 (0.86-0.96 at 27 h), so boundaries are less stable than they looked.
- **Snapshot timing matters.** Fitting a snapshot at 32 different times and scoring on the whole window gave shape R² from 0.229 to 0.308 (median 0.291, the same as geography alone at 0.290). Snapshots taken at 08:50 and 11:50, during the morning recovery, were worst on all 4 days; the spread of prices at the snapshot time explained little (correlation 0.33); the best matched the trajectory (0.309, in-sample). So a history fit is not clearly *better than a good snapshot*, but it removes the dependence on when the snapshot happened to be taken. See README section 6.
- **Limits:** 30 min resolution (`observed_at` is fetch time); each half of the split holds 2 days, so the scores are still noisy.

### Proposal: fit on a price trajectory (draft 11, confirmed in draft 13, implemented in draft 14 except the Pi re-freeze)

_Draft 14: steps 1-2 and 4-8 are in `scripts/` (step 3, the hour-of-day profile, was dropped). The frozen clusters on the Pi are still the snapshot ones until `freeze_clusters --force` is run there. Draft 13: confirmed. The 4-day results show a history fit is not clearly better than the best snapshot, but it does not depend on when the snapshot was taken, and that is the reason to do it._

1. **Trajectories.** For each station, hourly Régulier price over the last `FIT_DAYS` (3) days, or all the history there is if less, minus the hourly median of all mapped stations (the market cycle cancels; the premium remains). Move `hourly_prices` from `scripts/stats.py` to `scripts/history.py` so clustering does not import the page builder. Mask hours before a station's first price and after its `last_seen`.
2. **Features.** `[x_km, y_km, w × premium_trajectory / sqrt(H)]` with H the number of hourly samples, so `w` means "RMS premium difference in ¢" and does not drift as the window grows. Keep the clip (±15¢) and the 7-nearest median smoothing, applied per hour. Level stays in the trajectory: out of sample it scores like shape-only and the charts plot absolute prices. Start with `w = 3`; weights from 1.5 to 6 gave similar results at 27 h and at 4 days. A `level_weight` option allows shape-only experiments.
3. **Raw trajectory, not an hour-of-day profile** (open question 8, resolved). With at most 3 days, a 24-hour profile would average 3 values per hour, and only the raw trajectory was scored in the experiments. The profile is not planned.
4. **Eligibility.** Stations need at least 50% of the window's hours priced to take part; the others are placed by `assign_new_stations`.
5. **Freeze from the database.** `freeze()` builds its station table from `stations` (name, region, lat, lon, address are stored), so it needs no network and is reproducible from a backup.
6. **Quality report.** `report()` gains the mean within-cluster movement correlation; `freeze` and `preview` print in-sample and split-half out-of-sample R², and `freeze` refuses to run on fewer than `MIN_FIT_HOURS` (24) of history.
7. **Preview.** `scripts/preview.py` gains `--history` (default when enough data) and `--snapshot` for comparison.
8. **Re-fit policy.** Manual (`freeze --force`) once at least `MIN_FIT_HOURS` of history exist, always on the most recent `FIT_DAYS`; then whenever the quality report degrades.

Implement steps 1-2 and 6 first, compare the result against the frozen snapshot clusters with the quality report, then re-freeze on the Pi. The frozen snapshot clusters stay in use until then.

### Known limitations of the prototype

- A single snapshot cannot show whether stations in a cluster **move together over time**. That is the property the charts need. *Draft 11 proposed fitting on history; the 4-day analysis shows that changes the clusters only slightly and does not measurably improve them, so the snapshot clusters remain.*
- A few clusters are geographically wide (up to 40-65 km, e.g. Saint-Hyacinthe/Beloeil, Saint-Jérôme/Sainte-Agathe). A maximum diameter cap would split them.
- The Montréal island has no separate "Downtown" cluster: the price differences there are too small for the algorithm to pick up.

## Storage (implemented in `scripts/history.py`, draft 9)

- SQLite file on the Pi (WAL mode, daily `.backup`). About 10 days of retention, keeping the last price before the cutoff for each station.
- Tables:
  - `runs(run_id, fetched_at)`, one row per successful fetch
  - `stations(id, key, name, brand, address, region, lat, lon, cluster, first_seen, last_seen)`
  - `clusters(id, name, is_island)` (schema v2: the frozen regions)
  - `price_changes(station_id, gas_type, price, observed_at)`, inserted only when the price differs from the last stored value
- Size estimate: a few MB per day, far below the SD card capacity.
- As built: DB at `data/history.sqlite` (override with `ESSENCE_DB`, git-ignored); 10-day retention keeping the boundary price; a NULL price records a fuel no longer sold; only `REGIONS`-filtered stations are stored; renamed stations are matched by coordinates; daily backups (last 7) in `data/backups/`. The preview build (development branch) runs with `--no-history` so each fetch is recorded once. A history failure never blocks the map build (non-zero exit only).

## Chart values

- Cluster value: **as built** (draft 15), the mean with a min-max band, hourly points, Régulier only. The median with an IQR band was planned in draft 2-10 but is not implemented; accepted as-is for Phase 1. Price at time T = latest change at or before T.
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
5. **Bimodal clusters** (Saint-Jean-sur-Richelieu): accept the wide IQR band, or split by price level? Not yet checked on the 4-day data.
6. ~~Chart UI~~ resolved in draft 10: a dedicated statistics page (`stats.html`) linked from the map footer.
7. **Phase 2 colour scale:** fixed across time or rescaled per time step?
8. ~~24-hour profile vs raw trajectory~~ resolved in draft 13: raw hourly trajectory over up to the last 3 days. A profile would average only 3 values per hour and was not scored.
9. ~~Should Super join the fit?~~ resolved in draft 13: grades other than Régulier are out of scope.
10. **Which weight `w`?** 1.5-6 were indistinguishable at 27 h and at 4 days. Start with `w = 3` (trajectory scored best there, marginally); re-check against the frozen clusters with the quality report.
11. ~~Is the history-based clustering worth the work?~~ resolved in draft 13: yes, fit on up to the last 3 days of history, so the result does not depend on the time of day of a single snapshot. It is no better than the best snapshot, but it avoids the bad ones (README section 6).

## Build order

1. ~~Prototype the clustering on a snapshot~~ (done: `clustering.py` + `preview.py`, a developer-only Folium map opened in the browser for vetting clusters, built on `BaseMapRenderer` from `interactive_map.py`; end users never see the clusters themselves, only the charts)
2. ~~`history.py`: SQLite store (record run, change detection, retention)~~ (done: `scripts/history.py`, wired into `main.py`)
3. ~~Cluster freezing/assignment, integrated into `main.py`~~ (done, draft 10; no quality report yet; **needs rework** for history features, steps 6-8)
4. ~~Export series and add the chart~~ (done, draft 10: embedded in `stats.html`)
5. Phase 2: export per-station changes and add the slider. **On hold** (draft 15).
6. ~~History-based clustering, part 1~~ (done, draft 14): `hourly_prices` moved into `history.py`; trajectory features in `clustering.fit`; `freeze_clusters` fits from the database; quality report with split-half scores (see the proposal).
7. ~~`preview.py --history/--snapshot`~~ (done, draft 14).
8. Compare the history fit with the frozen snapshot clusters (quality report); then `freeze --force` on the Pi. **Next.**

## Changelog

- 2026-11-19: draft 15. Phase 1 accepted and committed as `88a0bb8` (statistics page, cluster charts, shared navbar and colourbar, dev-only Playwright dependency). The chart is the mean with min and max, not the median with IQR; that change is accepted for Phase 1. Phase 2 (time slider) is on hold. Build order step 8 (compare history fit with the frozen clusters, then re-freeze on the Pi) is unchanged and still open.
- 2026-11-19: draft 14. Clustering scripts match the plan. `history.py` gains `hourly_prices` (moved from `stats.py`), `epoch_seconds`, `fit_grid` and `span_hours`. `clustering.py` gains `history_features`, `hourly_premium`, `load_history_fit`, `cluster_quality` and `quality_lines`; `fit` and `fit_target` take an optional hourly premium matrix; `Params` gains `history_weight` (3) and `min_coverage` (0.5); `report` adds a within-cluster `corr` column given a premium matrix. `freeze_clusters` fits from the database (no network), over the last `FIT_DAYS` (3) days, refuses under `MIN_FIT_HOURS` (24), and prints in-sample and split-half scores; stations with under 50% of the hours priced are left NULL and placed by proximity. `preview.py` gains `--history` (default when at least 24 h exist) and `--snapshot`. Tested on a copy of the 95 h database: 20 clusters, 960 of 961 stations fitted, shape R² 0.301 in sample and 0.302 out of sample, within-cluster correlation 0.43 and 0.46. The frozen clusters on the Pi have not been re-frozen.
- 2026-11-19: draft 13. Decisions: (1) fit clusters on the hourly Régulier premium over the most recent 3 days, or as much as is available (resolves OQ 11 and OQ 8: raw trajectory, no hour-of-day profile); the 7-day re-run is no longer a precondition; (2) grades other than Régulier are out of scope (resolves OQ 9). The proposal is no longer on hold and `FIT_DAYS` is 3 (was 7). Open question 10 now starts at `w = 3`. Nothing in `scripts/` changed yet.
- 2026-11-19: draft 12. History grew to 191 runs (95 h, about 4 days); `export_history.py`, `analysis.py` and `ward_experiment.py` re-run, README and plan updated. The 00:20 jump repeats on all 4 nights. History-based features (trajectory, shape-only) do **not** clearly beat the snapshot or geography alone (out-of-sample shape R² 0.30-0.31 for the four best variants; window-average premium lower at 0.27), and clusterings agree less with each other than at 27 h (adjusted Rand 0.80-0.89). The draft 11 decision to fit on history is therefore on hold; steps 1-8 of the proposal are not implemented and the frozen snapshot clusters stay. `analysis.py` now drops stations that joined mid-window (962 and 963), which broke the SVD. The README's PC1/PC2 description was rewritten for the 4-day fit (PC2 is a slow drift, not a mid-morning bump). New `snapshot_timing.py` tests whether the snapshot time matters: it does (shape R² 0.229-0.308 across 32 snapshot times, median equal to geography). Nothing in `scripts/` changed.
- 2026-11-16: draft 11. 27 h of Pi history analysed; scripts, data and figures in `design/history/clustering/`. Plan moved from `.agents/plan.md` to `design/history/plan.md`. Decision: clusters are fitted on the price history (trajectory features), not one snapshot; the Sainte-Thérèse / Sainte-Marthe-sur-le-Lac split is an observation, not a requirement. Finding: history features change the clusters only slightly at 27 h (adjusted Rand 0.86-0.91 against the snapshot clusters), so re-validate at 3 and 7 days. Corrected drift between plan and code (8 km edges, α = 1.5, 19 clusters, premium against the overall median, `clusters` table and `region` column in the schema). Nothing in `scripts/` changed yet.

- 2026-11-15: draft 10. Statistics page implemented. Clusters are frozen into the DB by `scripts/freeze_clusters.py` (schema v2 adds a `clusters` table; `stations.cluster` is -1 for unclustered, NULL for not yet placed; new stations join the nearest clustered station within 8 km). `scripts/stats.py` embeds hourly per-cluster `{n, sum, min, max}` series and the current stations into `build/stats.html` (template `assets/stats.html`, Chart.js + Leaflet from CDNs), so there is no separate `history.json` yet. Chart shows min, max and mean (not median/IQR), Régulier only. Q6 resolved: a dedicated page, linked from the map footer. `build_colormap` in `interactive_map.py` is shared by the map and the page. `comments.guidelines.md` now covers JavaScript only; Python follows the `python-code-guidelines` skill.
- 2026-11-15: draft 9. History store implemented (`scripts/history.py`). `interactive_map.py` split into `main.py` (entry point, single fetch) and `scripts/interactive_map.py` (map code, `REGIONS`). GitHub Actions workflow removed; the Pi (cron -> `assets/deploy-page`) is the only builder. README documents the topology and Pi setup.
- 2026-11-15: draft 8. Island naming: added a Centre-Ville reference point (replacing "Centre", which was never a primary name in the snapshot and overlapped it). Clusters now carry a second area name when 25%+ of their island stations are nearest to it, e.g. "Montréal (Nord / Centre-Ville)". At 25 clusters the island splits out a standalone Centre-Ville cluster.
- 2026-11-15: draft 7. `preview.py` now renders a Folium map (one toggleable coloured layer per cluster, legend, hover tooltips) opened in the browser, replacing the matplotlib window. `interactive_map.py` gained `BaseMapRenderer` (shared page chrome) and a `__main__` guard, and now owns `REGIONS` for both the map and the clustering. Municipality names under 20% of a cluster are dropped from its name. README documents the clustering. Added the "keep this plan current" rule.
- 2026-11-15: draft 6. Island clusters now use Montréal-style names (West Island, Centre-Ouest, Sud-Ouest, Centre, Nord, Est) via nearest-reference-point matching. At the default 19-cluster target the island has 6 clusters.
- 2026-11-14: draft 5. Cluster vetting is a developer-only tool (`preview.py`, interactive matplotlib window with hover details and a per-cluster quality table). The HTML cluster map idea was dropped. Tuned parameters are now the defaults in `clustering.py`.
- 2026-11-14: draft 4. Size cap and land-linked regions added; island split into 4 clusters with compass names; invalid-coordinate station filtered.
- 2026-11-14: draft 3. Min size 12 and rural-unclustered rule confirmed. Prototype run on the snapshot; findings on station IDs, data quirks and first cluster results added. Open questions updated.
- 2026-11-14: draft 2. Clusters changed from hand-defined to data-driven (frozen after fitting).
- 2026-11-14: draft 1 created.
