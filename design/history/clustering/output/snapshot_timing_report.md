# Snapshot timing experiment

32 snapshots, one every 3 hours, each fitted alone (weight 1.5, about 19 clusters) and scored on the whole window.

| | Shape R² | Level R² | Corr |
|---|---|---|---|
| Snapshot, worst | 0.229 | 0.170 | 0.38 |
| Snapshot, median | 0.291 | 0.215 | 0.40 |
| Snapshot, best | 0.308 | 0.237 | 0.44 |
| Geography only | 0.290 | 0.211 | 0.39 |
| Trajectory (weight 3, fitted on the whole window: in-sample) | 0.309 | 0.230 | 0.44 |

Snapshots that beat geography on shape R²: 17 of 32. Snapshots within 0.01 of the trajectory on shape R²: 6 of 32.

Best snapshot: Thu 14:50 (price spread std 7.7¢). Worst: Wed 08:50 (std 6.1¢).
Correlation between the spread of prices at the snapshot and its shape R²: 0.33 (std), 0.23 (IQR).

Shape R² by time of day (mean over days):

| Hour of day | Snapshots | Shape R² |
|---|---|---|
| 00:00-05:59 | 8 | 0.289 |
| 06:00-11:59 | 8 | 0.260 |
| 12:00-17:59 | 8 | 0.297 |
| 18:00-23:59 | 8 | 0.295 |
