# Quebec Gas Price Map

An automated web application that visualizes gas prices in Quebec (specifically Montréal, Laval, Montérégie, Lanaudière and Laurentides). A Raspberry Pi compiles the latest pricing data into clean, interactive maps, keeps a history of price changes in a local SQLite database, and publishes the maps to GitHub Pages.

## Project Topology

```
 cron (every 30 min, on the Raspberry Pi)
   └─ assets/deploy-page
        ├─ main branch  ─ main.py ──┬─ fetch regieessencequebec.ca (once)
        │                           ├─ record price changes ─► data/history.sqlite (Pi only)
        │                           └─ render index/super/diesel.html ─► build/ ─► force-push to `build` branch
        └─ development  ─ main.py --no-history ─► build/ ─► force-push to `preview` branch
                                                                     │
                                       GitHub Pages serves the `build` and `preview` branches
```

1. **Data source:** live station coordinates and prices from [regieessencequebec.ca](https://regieessencequebec.ca/stations.geojson.gz).
2. **Build:** [main.py](main.py) fetches the feed **once**, parses prices for Regular/Super/Diesel, filters for the mapped regions, records the history, and renders three maps with `folium` (the map code lives in [scripts/interactive_map.py](scripts/interactive_map.py)).
3. **History:** [scripts/history.py](scripts/history.py) stores price *changes* (not 30-minute snapshots) in a SQLite database on the Pi. The database is never committed to Git or published. Only the `build` and `preview` branches, which contain generated HTML, are pushed to GitHub.
4. **Scheduling and deployment:** the Pi's cron runs [assets/deploy-page](assets/deploy-page) every 30 minutes. It builds the production site from `main`, pushes it to the `build` branch, then builds the `preview` site from `development` and pushes it to the `preview` branch. GitHub Pages hosts those branches; there are no GitHub Actions. The preview build runs with `--no-history`, so each fetch is recorded exactly once, by the production code.
5. **Failure behaviour:** if recording history fails, the maps are still rendered and deployed, and `main.py` exits with a non-zero code so the problem shows in the log.

## Price History

The database (`data/history.sqlite`, or the path in the `ESSENCE_DB` environment variable) uses WAL mode and has four tables:

| Table | Contents |
|---|---|
| `runs` | One row per successful fetch (UTC timestamp). |
| `stations` | One row per station: key (name and coordinates at 5 decimals), name, brand, address, region, coordinates, first/last seen, and a nullable `cluster` column (-1 = deliberately unclustered, NULL = not placed yet). |
| `clusters` | The frozen regions: id, name and an island flag. |
| `price_changes` | `(station, gas type, price, observed_at)`, inserted only when a price differs from the last stored value. A NULL price means the station stopped offering that fuel. |

- The price at time T is the latest change at or before T.
- The feed has no station ID, so stations are keyed on name and coordinates. A renamed station at the same coordinates keeps its history.
- Each run prunes data older than 10 days, but keeps the last price at or before the cutoff for every station and fuel.
- Once per day the database is copied to `data/backups/history-YYYY-MM-DD.sqlite` (the last 7 are kept) using SQLite's online backup, which is safe while the build is running.

## Verbose Marker Selection Logic

To prevent map overcrowding, the interactive map limits the rendering of verbose speech-bubble price markers based on station density:
- **Density Threshold:** If there are more than 300 stations visible in the current viewport, all verbose markers are disabled and rendered as simple colored dots.
- **Selection Process:** When the viewport contains 300 or fewer stations, a greedy algorithm selects a dynamic number of stations (based on screen size breakpoints) to display as verbose markers:
  - **xs/sm** (< 768px): max 8 verbose markers
  - **md** (768px to 991px): max 14 verbose markers
  - **lg** (992px to 1199px): max 20 verbose markers
  - **xl+** (>= 1200px): max 25 verbose markers
  
  The selection algorithm prioritizes markers as follows:
  1. **Center Region Priority:** Stations within a responsive central region (radius of 35% of the minimum of map width and height) are prioritized first.
  2. **Initial Seed:** The station closest to the map center is selected first.
  3. **Multi-Objective Scoring:** Subsequent verbose markers are selected one by one to maximize a combined score:
     $$\text{Score} = 0.4 \times \text{normalized\_dist} + 0.4 \times \text{normalized\_price\_diff} + 0.2 \times \text{cheapness}$$
     where `normalized_dist` is the minimum distance to any already selected verbose marker (prioritizing geographic spread), `normalized_price_diff` is the minimum price difference to any already selected verbose marker (prioritizing price range diversity), and `cheapness` is defined using a linear mapping of the price's z-score within the visible station sample:
     $$\text{cheapness} = \frac{z_{\max} - z}{z_{\max} - z_{\min}}, \quad z = \frac{\text{price} - \mu}{\sigma}$$
     *(Note: If $z_{\max} = z_{\min}$, then $\text{cheapness} = 1.0$ for all stations).*
  4. **Collision Check:** Candidates are verified against existing verbose markers to prevent overlapping before placement. If slots remain, the same logic is applied to stations outside the central region.

## Local Setup & Execution

This project uses [uv](https://github.com/astral-sh/uv), a fast Python package installer and resolver.

### Prerequisites

- Python 3.12+
- `uv` installed on your machine.
  - *On Windows (PowerShell):*
    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
  - *Alternatively, via pip:*
    ```bash
    pip install uv
    ```

### Running Locally

1. **Clone the repository:**
   ```bash
   git clone git@github.com:chanlan1105/gas-price-map.git essence
   cd essence
   ```

2. **Sync and install dependencies:**
   This command automatically creates a virtual environment (`.venv`) and installs the exact versions of all packages specified in `uv.lock`:
   ```bash
   uv sync [--no-dev]
   ```

   In production environments, use the `--no-dev` flag to avoid adding heavy dev dependencies.

3. **Generate the interactive maps:**
   Execute the build script inside the synchronized virtual environment:
   ```bash
   uv run python main.py --no-history
   ```
   This will output `index.html`, `super.html` and `diesel.html` in the `build/` directory. Leave out `--no-history` to also record the prices in the history database (created under `data/` on first use; set `ESSENCE_DB` to use another file, e.g. when experimenting).

4. **View the map:**
   Open the generated `index.html` in any web browser to view the interactive map.

## Station Clustering (developer tool)

`scripts/clustering.py` groups stations into price areas, so that later features (price history charts) can report one median price per area. Nothing in the deployed map depends on it yet. The same station selection as the map is used (`REGIONS` in `scripts/interactive_map.py`).

> [!NOTE]
> **Clusters are fitted on price history.** A single price snapshot cannot tell whether stations in a cluster *move together over a day*, and a snapshot's quality depends on the time of day it was taken, so the clusters are fitted on each station's hourly premium over the last 3 days of the history database (or all of it, if shorter, and at least 24 hours). The analysis, with its scripts, data and figures, is in [design/history/clustering](design/history/clustering/README.md), and the design and status are in [design/history/plan.md](design/history/plan.md). Only Régulier is clustered.

### How it works

1. **Features:** each station becomes `(x_km, y_km, 3 × premium trajectory / √hours)`. The trajectory is the station's hourly Régulier price minus the market median at the same hour (so the daily price cycle cancels), clipped to ±15¢ and smoothed with the median of the 7 nearest stations at each hour, so a single outlier station doesn't steer the clusters. Dividing by √hours makes the weight 3 mean "an RMS premium difference of 3¢ counts as much as 1 km" whatever the window length. Stations with prices for under half of the window are not fitted and are placed by proximity afterwards. A preview with `--snapshot` uses the old features, `(x_km, y_km, 1.5 × smoothed premium)` from the current prices only.
2. **Connectivity graph:** every station is linked to its 6 nearest neighbours in the same region (edges over 8 km are dropped). Laurentides and Lanaudière may share clusters since they're connected by land; Montréal, Laval and Montérégie are separated by rivers.
3. **Clustering:** Ward agglomerative clustering restricted to that graph, so clusters are geographically contiguous. The Ward threshold is searched until it yields about the target number of clusters (default 19).
4. **Clean-up:** clusters under 12 stations merge into their nearest neighbour; clusters over 75 stations are re-split (this is what divides the dense Montréal island). Groups that remain too small or isolated, typically rural stations, stay unclustered.
5. **Naming:** Montréal-island clusters take the nearest local area name (West Island, Centre-Ouest, Sud-Ouest, Centre-Ville, Centre-Est, Nord, Est) from the reference points in `ISLAND_ANCHORS`. A cluster that also holds a substantial share (25%+) of stations nearer to another area gets both names, e.g. `Montréal (Nord / Centre-Ville)`, most common first (max two). A cluster named exactly `Centre-Est / Centre-Ouest` (either order) is renamed `Centre`. Other clusters are named after their main municipalities, ignoring any with under 20% of the cluster's stations.

### Previewing the clusters

Run from the repository root:

```bash
uv run python -m scripts.preview [stations.geojson] [--history | --snapshot] [--gas Régulier] [--clusters 19] [--no-open]
```

By default this fits on the stored history (the same fit as the freeze below, read from the database) when it holds at least 24 hours; `--snapshot` fetches the live feed instead (a GeoJSON file always means a snapshot fit), to compare the two. It prints a per-cluster quality table (size, median price, IQR, diameter, and for a history fit the mean correlation of movement between the cluster's stations), the in-sample and out-of-sample scores of a history fit (fitted on one half of the window and scored on the other), and writes a Folium map to `<temp dir>/essence_clusters/clusters.html`, which opens in your browser. Each cluster is a separate layer with its own colour; hover a station for its details. `--no-open` skips opening the browser. The output is never written to `build/`, so it isn't deployed.

> [!NOTE]
> The preview recomputes the clusters from the current history every time, so names and boundaries can shift between runs. The regions used on the site are frozen separately (below).

### Freezing the regions

The statistics page uses the clusters as its regions, so they are fitted once and stored in the history database:

```bash
uv run python -m scripts.freeze_clusters [--force]
```

This reads the history database (no network), fits about 19 clusters on the last 3 days of hourly Régulier prices, refuses to run on less than 24 hours of history, prints the quality scores, and writes the `clusters` table (name, and whether the cluster is on the Montréal island) and every station's `cluster`. It refuses to run again unless `--force` is given, because refitting changes the regions. Stations that appear later join the cluster of their nearest clustered station (within 8 km, otherwise they stay unclustered) during each history run. Run this once on the Pi after deploying the new version.

## Statistics Page

`stats.html` (linked as "Stats" in the map footer) shows, for one region or all regions, the hourly minimum, maximum and mean Régulier price over 24 hours, 3 days or 7 days. For a single region it also shows the difference from the Greater Montréal average, and, for island regions, from the rest of the island. A minimap colours only the selected region's stations with the same colour scale as the main map.

- [scripts/stats.py](scripts/stats.py) rebuilds each station's hourly price from the stored changes (`history.hourly_prices`, also used by the clustering), summarizes it per cluster, and embeds the result in the page built from [assets/stats.html](assets/stats.html). The database is only read, so the `--no-history` preview build also gets the page.
- The page needs the frozen clusters. Without them it only offers "All regions".
- On narrow screens the minimap fills the screen, the region selector floats over it, and the chart and figures open as a bottom sheet.

## Dependencies

All packages and version constraints are defined in `pyproject.toml`.

To add, remove, or update dependencies, use the `uv add` or `uv remove` commands, which will automatically keep `pyproject.toml` and `uv.lock` aligned.

### Dev Dependencies

`playwright` is installed as a dev dependency to allow agents to verify the UI. Upon setup, download the Playwright browsers:

```
uv run playwright install
```

## Raspberry Pi Setup

These steps prepare a fresh Raspberry Pi (Raspberry Pi OS / Debian) to build, record and publish the site.

1. **System packages:**
   ```bash
   sudo apt-get update
   sudo apt-get install git g++ sqlite3
   ```
   `sqlite3` is only needed to inspect the database by hand.

2. **Time zone and clock:** the history is timestamped, so keep the clock correct.
   ```bash
   sudo timedatectl set-timezone America/Toronto
   timedatectl   # "System clock synchronized: yes"
   ```
   Timestamps in the database are always stored in UTC.

3. **Install `uv`:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   `assets/deploy-page` expects it at `~/.local/bin/uv`.

4. **GitHub access for publishing:** `deploy-page` pushes to `git@github-essence:chanlan1105/gas-price-map.git`, where `github-essence` is an SSH host alias. Create a key and register it as a **deploy key with write access** on the repository (Settings → Deploy keys):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/essence_deploy -C "essence-pi" -N ""
   cat >> ~/.ssh/config <<'EOF'
   Host github-essence
       HostName github.com
       User git
       IdentityFile ~/.ssh/essence_deploy
       IdentitiesOnly yes
   EOF
   cat ~/.ssh/essence_deploy.pub   # paste into GitHub
   ssh -T git@github-essence       # accept the host key; should greet you
   ```

5. **Clone and install:**
   ```bash
   git clone git@github-essence:chanlan1105/gas-price-map.git ~/essence
   cd ~/essence
   git config user.name "essence-pi"
   git config user.email "essence-pi@localhost"   # the deploy script makes commits
   uv sync --no-dev
   chmod +x assets/deploy-page
   mkdir -p logs
   ```
   The deploy script switches between the `main` and `development` branches, so both must exist and the working tree must stay clean.

6. **Test a run by hand** before scheduling it:
   ```bash
   ./assets/deploy-page
   sqlite3 data/history.sqlite "select count(*) from price_changes"
   ```
   The first run fills the database with every station's current prices; later runs add only changes.

7. **Schedule it every 30 minutes** with `crontab -e`:
   ```cron
   */30 * * * * flock -n /tmp/essence.lock /home/pi/essence/assets/deploy-page >> /home/pi/essence/logs/deploy.log 2>&1
   ```
   Use the absolute path of your clone, since cron does not run in your home directory. `flock -n` skips a run if the previous one is still going, so two builds never write the database or the `build/` folder at once.

8. **Keep the log from growing forever:** add `/etc/logrotate.d/essence`:
   ```
   /home/pi/essence/logs/deploy.log {
       weekly
       rotate 4
       compress
       missingok
       notifempty
   }
   ```

9. **GitHub Pages:** in the repository settings under **Pages**, set the source to **Deploy from a branch** and pick the `build` branch (and `preview` if you want the preview site).

### Looking after the history database

- **Where:** `data/history.sqlite` (plus `-wal` and `-shm` files while the build runs). The folder is git-ignored and exists only on the Pi.
- **Backups:** `data/backups/` holds the last 7 daily copies. Copy that folder off the Pi occasionally if the history matters to you; an SD card failure would otherwise lose it.
- **Restore:** stop cron, then `cp data/backups/history-YYYY-MM-DD.sqlite data/history.sqlite` and delete any `history.sqlite-wal` and `-shm` files.
- **Check:** `sqlite3 data/history.sqlite "pragma integrity_check; select max(fetched_at) from runs;"`. The latest run should be under an hour old.
- **SD card wear:** each run writes a handful of rows, and WAL mode with `synchronous=NORMAL` keeps the writes small.

### Manual deploys

Run `./assets/deploy-page` on the Pi at any time to rebuild and publish immediately.
