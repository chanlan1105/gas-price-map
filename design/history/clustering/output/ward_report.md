# Ward experiment

961 stations, about 19 clusters, graph and size limits from `Params()`. Scores are averaged over the two folds (fit on one half of the window, score on the other).

| Method | Weight | In-sample shape R² | **Out-of-sample shape R²** | **Out-of-sample level R²** | Out-of-sample corr | Median / max diameter (km) | Clusters | Unclustered |
|---|---|---|---|---|---|---|---|---|
| geography | 0 | 0.299 | **0.299** | **0.210** | 0.40 | 19 / 57 | 21 | 102 |
| snapshot | 1.5 | 0.314 | **0.313** | **0.231** | 0.42 | 23 / 57 | 19 | 102 |
| snapshot | 3 | 0.316 | **0.312** | **0.227** | 0.42 | 23 / 57 | 19 | 102 |
| level | 1.5 | 0.275 | **0.275** | **0.207** | 0.42 | 22 / 57 | 19 | 102 |
| level | 3 | 0.273 | **0.274** | **0.208** | 0.45 | 25 / 44 | 19 | 102 |
| trajectory | 1.5 | 0.305 | **0.302** | **0.229** | 0.43 | 22 / 50 | 19 | 102 |
| trajectory | 3 | 0.315 | **0.311** | **0.233** | 0.45 | 23 / 50 | 19 | 102 |
| trajectory | 6 | 0.310 | **0.310** | **0.223** | 0.44 | 23 / 57 | 19 | 102 |
| shape | 3 | 0.297 | **0.296** | **0.216** | 0.43 | 23 / 57 | 19 | 102 |
| shape | 6 | 0.301 | **0.298** | **0.209** | 0.43 | 22 / 57 | 20 | 102 |
| shape | 10 | 0.283 | **0.283** | **0.203** | 0.43 | 23 / 57 | 19 | 102 |

## Agreement between clusterings fitted on the whole window

Adjusted Rand index between each pair (1 = same clusters). Stations unclustered in both are ignored.

| | geography | snapshot | level | trajectory | shape |
|---|---|---|---|---|---|
| geography | 1.00 | 0.83 | 0.85 | 0.80 | 0.81 |
| snapshot | 0.83 | 1.00 | 0.84 | 0.85 | 0.82 |
| level | 0.85 | 0.84 | 1.00 | 0.88 | 0.81 |
| trajectory | 0.80 | 0.85 | 0.88 | 1.00 | 0.89 |
| shape | 0.81 | 0.82 | 0.81 | 0.89 | 1.00 |
