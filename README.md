# Quebec Gas Price Map

An automated, serverless web application that visualizes gas prices in Quebec (specifically Montréal, Laval, Montérégie, and Laurentides regions). It compiles the latest pricing data into a clean, interactive map and deploys it to GitHub Pages.

## Project Architecture & Workflow

The application operates as a serverless pipeline:
1. **Data Source:** Fetches live station coordinates and prices from [regieessencequebec.ca](https://regieessencequebec.ca/stations.geojson.gz).
2. **Processing:** The [interactive_map.py](file:///c:/Users/lucas/Documents/Lucas/essence/interactive_map.py) script fetches the GeoJSON data, cleans up prices for Regular/Super/Diesel, filters for specific regions, and constructs an interactive map using `folium`.
3. **Output:** Generates a standalone, responsive `index.html` featuring a custom info panel with data refresh timestamps.
4. **Deployment:** A GitHub Actions workflow ([update_map.yml](file:///c:/Users/lucas/Documents/Lucas/essence/.github/workflows/update_map.yml)) runs every 30 minutes to rebuild the map and deploy it directly to GitHub Pages without committing built HTML files back to your source branches.

---

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
   git clone <your-repo-url>
   cd essence
   ```

2. **Sync and install dependencies:**
   This command automatically creates a virtual environment (`.venv`) and installs the exact versions of all packages specified in `uv.lock`:
   ```bash
   uv sync
   ```

3. **Generate the interactive map:**
   Execute the processing script inside the synchronized virtual environment:
   ```bash
   uv run python interactive_map.py
   ```
   This will output a new `index.html` file in the project root.

4. **View the map:**
   Open the generated `index.html` in any web browser to view the interactive map.

---

## Dependencies

All packages and version constraints are defined in `pyproject.toml`:

* **Data Fetching:** `requests`
* **Data Processing & Geospatial:** `geopandas`, `pandas`, `pyarrow`, `fiona`, `tzdata`
* **Visualization & Map Rendering:** `folium`, `branca`

To add, remove, or update dependencies, use the `uv add` or `uv remove` commands, which will automatically keep `pyproject.toml` and `uv.lock` aligned.

---

## GitHub Actions & CI/CD

* **Schedule:** The cron job runs **every 30 minutes** (`*/30 * * * *`).
* **Manual Trigger:** Can be triggered manually via the Actions tab in your repository (`workflow_dispatch`).
* **Cache Management:** Employs `astral-sh/setup-uv` with caching enabled on `uv.lock` for rapid execution speeds.
* **Serverless Deployment:** Uploads only the compiled `index.html` as a Pages artifact and deploys it using official GitHub Actions (`actions/upload-pages-artifact` and `actions/deploy-pages`). This avoids committing built HTML files back to your source branches.

> [!IMPORTANT]
> **Enabling GitHub Pages Deployment:**
> To ensure the GitHub Actions workflow successfully publishes the site:
> 1. Go to your repository settings on GitHub.
> 2. Navigate to **Pages** in the sidebar.
> 3. Under **Build and deployment**, set the **Source** to **GitHub Actions** (instead of Deploy from a branch).
