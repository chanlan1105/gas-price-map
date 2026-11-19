# Analysis report (Régulier)

## 1. Coverage

- Runs: 191, Sun 17:50 to Thu 17:20 local (95 h).
- Gap between runs: median 30.0 min, max 60.0 min, 1 gaps over 45 min.
- Stations: 963; left the feed before the last run: 1.
- Stations per region: Montérégie 387, Montréal 226, Laurentides 190, Lanaudière 89, Laval 71.
- Stations per brand: Esso 243, Shell 171, Petro-Canada 158, Ultramar 144, Couche-Tard 77, Harnois 54, Sonic 21, Crevier 15.

| Fuel | Changes after run 1 | Stations that changed | Median changes per changer |
|---|---|---|---|
| Diesel | 1339 | 658 | 2 |
| Régulier | 13337 | 921 | 14 |
| Super | 13089 | 915 | 14 |

`observed_at` is the fetch time, so timing resolution is one run (30 min).

## 2. The daily cycle

Market median (all mapped stations), every 3 hours:

| Local time | Median ¢ | 10th pct | 90th pct |
|---|---|---|---|
| Sun 17:50 | 162.9 | 149.9 | 168.9 |
| Sun 20:50 | 161.9 | 149.9 | 168.9 |
| Sun 23:50 | 162.9 | 149.9 | 169.9 |
| Mon 02:50 | 167.9 | 152.9 | 168.9 |
| Mon 05:50 | 167.9 | 153.9 | 168.9 |
| Mon 08:50 | 164.9 | 151.9 | 167.9 |
| Mon 11:50 | 163.9 | 149.9 | 167.9 |
| Mon 14:50 | 161.9 | 146.9 | 167.9 |
| Mon 17:50 | 158.9 | 146.9 | 167.9 |
| Mon 20:50 | 158.9 | 146.9 | 167.9 |
| Mon 23:50 | 158.9 | 146.9 | 167.9 |
| Tue 02:50 | 167.9 | 151.2 | 167.9 |
| Tue 05:50 | 167.9 | 151.9 | 167.9 |
| Tue 08:50 | 164.9 | 150.5 | 167.9 |
| Tue 11:50 | 161.9 | 148.9 | 167.9 |
| Tue 14:50 | 159.9 | 147.9 | 166.9 |
| Tue 17:50 | 157.9 | 146.9 | 166.9 |
| Tue 20:50 | 157.9 | 146.9 | 166.9 |
| Tue 23:50 | 157.9 | 146.9 | 166.9 |
| Wed 02:50 | 163.9 | 149.9 | 164.9 |
| Wed 05:50 | 163.9 | 149.9 | 164.9 |
| Wed 08:50 | 162.9 | 149.9 | 164.9 |
| Wed 11:50 | 159.9 | 148.9 | 163.9 |
| Wed 14:50 | 158.9 | 144.9 | 163.9 |
| Wed 17:50 | 154.9 | 143.9 | 163.9 |
| Wed 20:50 | 153.9 | 142.9 | 163.9 |
| Wed 23:50 | 154.9 | 142.9 | 164.9 |
| Thu 02:50 | 164.9 | 148.9 | 164.9 |
| Thu 05:50 | 164.9 | 149.9 | 164.9 |
| Thu 08:50 | 161.9 | 145.9 | 164.9 |
| Thu 11:50 | 157.9 | 142.9 | 164.9 |
| Thu 14:50 | 154.9 | 141.9 | 163.9 |

Rises of 8¢ or more, per run (runs with 5+): Sun 22:20 18, Sun 22:50 15, Sun 23:20 22, Mon 00:20 153, Mon 00:50 39, Mon 01:20 8, Mon 06:20 10, Mon 06:50 5, Mon 22:20 25, Mon 22:50 20, Mon 23:20 32, Mon 23:50 6, Tue 00:20 236, Tue 00:50 48, Tue 01:20 5, Tue 05:50 11, Tue 06:20 12, Tue 06:50 8, Tue 22:20 11, Tue 22:50 14, Tue 23:20 21, Tue 23:50 6, Wed 00:20 159, Wed 00:50 47, Wed 01:20 5, Wed 05:50 6, Wed 06:20 10, Wed 06:50 8, Wed 21:50 6, Wed 22:20 25, Wed 22:50 32, Wed 23:20 27, Thu 00:20 232, Thu 00:50 49, Thu 01:20 7, Thu 05:50 9, Thu 06:20 18, Thu 07:20 10, Thu 07:50 5.
Busiest run for any change: Tue 00:20 with 274 stations changing.
Stations whose price never changed in the window: 42.
Step sizes (¢): 1st pct -18, 5th -7, median -2, 95th 13, 99th 24.

Regional mean price relative to the start (¢), every 4.5 hours:

| Region | Sun 17:50 | Sun 22:20 | Mon 02:50 | Mon 07:20 | Mon 11:50 | Mon 16:20 | Mon 20:50 | Tue 01:20 | Tue 05:50 | Tue 10:20 | Tue 14:50 | Tue 19:20 | Tue 23:50 | Wed 04:20 | Wed 08:50 | Wed 13:20 | Wed 17:50 | Wed 22:20 | Thu 02:50 | Thu 07:20 | Thu 11:50 | Thu 16:20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lanaudière | +0.0 | -0.3 | +3.8 | +3.6 | -0.4 | -3.2 | -4.5 | +2.2 | +3.0 | -0.1 | -1.9 | -4.3 | -3.7 | -0.3 | -1.6 | -5.0 | -8.1 | -8.6 | -1.4 | -0.4 | -4.4 | -10.7 |
| Laurentides | +0.0 | -0.3 | +2.8 | +3.0 | +1.8 | -0.8 | -1.5 | +2.1 | +2.2 | +1.9 | -0.5 | -2.3 | -1.7 | -0.0 | -1.0 | -2.6 | -5.1 | -5.5 | -2.0 | -2.2 | -4.8 | -6.7 |
| Laval | +0.0 | -0.1 | +8.6 | +9.1 | +4.2 | +0.5 | -1.4 | +8.1 | +8.4 | +6.2 | +2.5 | -0.5 | -0.1 | +5.0 | +3.7 | +0.3 | -4.2 | -4.6 | +4.5 | +5.4 | -0.1 | -3.5 |
| Montréal | +0.0 | -0.7 | +4.5 | +4.2 | +1.5 | -1.5 | -3.9 | +3.9 | +4.0 | +1.2 | -1.3 | -4.5 | -4.2 | +0.4 | -0.1 | -2.2 | -6.4 | -7.2 | +0.8 | +1.0 | -2.3 | -6.2 |
| Montérégie | +0.0 | -0.0 | +3.5 | +3.4 | +0.1 | -2.4 | -3.1 | +1.5 | +2.0 | -0.0 | -2.1 | -3.4 | -3.2 | -0.3 | -1.1 | -4.0 | -5.8 | -6.0 | -1.8 | -1.6 | -5.2 | -7.0 |

## 3. Level versus movement

- Spread of stations' average premium (level): std 7.6¢.
- Typical temporal wobble of a station's premium: mean std 3.8¢ (10th-90th pct 2.3-5.4¢).
- Share of movement variance explained by principal components 1-5: 49%, 10%, 7%, 5%, 4%.
  The first two components are a handful of numbers that describe most stations, so the dynamics are low-dimensional.

## 4. Who moves with whom

Mean correlation of two stations' movement, by the distance between them:

| Distance (km) | Pairs | All | Same brand | Different brand |
|---|---|---|---|---|
| 0-1 | 724 | 0.63 | 0.76 | 0.61 |
| 1-2 | 1431 | 0.46 | 0.54 | 0.45 |
| 2-4 | 4647 | 0.34 | 0.42 | 0.32 |
| 4-8 | 14461 | 0.21 | 0.27 | 0.19 |
| 8-16 | 49220 | 0.10 | 0.14 | 0.09 |
| 16-40 | 178597 | 0.13 | 0.15 | 0.13 |
| 40-200 | 211240 | 0.25 | 0.22 | 0.25 |

Beyond 40 km the correlation rises again. Of those pairs, same-region pairs average 0.37 and different-region pairs 0.22. Region only partly explains it, and the cause is not established (possibly a province-wide pattern shared by distant areas). It does not matter for contiguous clusters, which only use neighbours within a few km.

Share of the variation between stations explained by each grouping (adjusted R², 5 km grid cells for area):

| Feature | Brand | Area (grid cell) | Region |
|---|---|---|---|
| Average premium (level) | 0.11 | 0.45 | 0.04 |
| Premium volatility | 0.03 | 0.58 | 0.11 |
| Decay rate after the midnight jump (¢/h) | 0.02 | 0.43 | 0.02 |
| Size of the midnight jump (¢) | 0.12 | 0.34 | 0.04 |

Correlation between a station's value and the mean of its six nearest neighbours: average premium 0.57, premium volatility 0.76, decay rate after the midnight jump 0.57, size of the midnight jump 0.61.

