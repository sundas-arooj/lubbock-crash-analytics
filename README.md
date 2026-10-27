# Lubbock district crash analytics

Crash-level figures from a TxDOT Crash Records Information System extract for the Lubbock district. The export is person-level: one crash is repeated once for every person involved. This project collapses those rows, then serves severity, contributing factor, and time breakdowns through a small API and a one-page profile.

The extract already limits the records to injury and fatal crashes (K, A, B, and C) in crash years 2020–2026. These figures describe that file. They are not official TxDOT statistics.

From that file, after collapsing to one row per crash: **24,261 crashes** (from 67,906 person rows), of which 624 were fatal (K), 1,546 suspected serious (A), 7,224 suspected minor (B), and 14,867 possible injury (C). Those fatal crashes account for **707 deaths**. The most common coded factor is failure to control speed, listed on 5,559 crashes. The notebook has the supporting checks.

## Run it locally

The project virtual environment is `.venv`. Install packages only there.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/process_data.py
uvicorn app.api:app --reload
```

Open http://127.0.0.1:8000 for the profile, or http://127.0.0.1:8000/docs for the interactive API reference.

`process_data.py` reads `district_crashes.csv`, skips the disclaimer at the top, keeps one row per crash, and writes `data/processed/crashes.db`. Run it again after the CSV changes. Stop the API first so Windows can replace the database file.

The exploratory notebook is `eda/crash_eda.ipynb`. From the activated environment:

```powershell
jupyter notebook eda/crash_eda.ipynb
```

## API

All filters are optional. `county`, `severity`, and `road_class` are case-insensitive. `severity` is `K`, `A`, `B`, or `C`. Add `format=csv` to the severity, factor, and trend routes for a download.

| Route | What it returns |
|---|---|
| `GET /health` | Process status, crash count, district, extract date |
| `GET /api/filters` | Counties, years, road classes, and severities |
| `GET /api/severity` | Crash counts by severity |
| `GET /api/factors?limit=5` | Contributing factors ranked by crash frequency |
| `GET /api/trends?grain=month` | Counts by month, year, or hour (`grain=year` or `grain=hour`) |
| `GET /api/locations` | Coordinates for the map |
| `GET /api/overview` | Severity, top five factors, monthly trend, and hour of day together |

Example: fatal crashes in Lubbock County during 2024.

```text
GET /api/factors?county=Lubbock&year=2024&severity=K
```

## Tests

```powershell
python -m pytest
```

The fixture tests cover the cleaning rules. One test reads the full extract and checks the published totals: 67,906 person rows and 24,261 crashes.

## How the numbers are defined

- A crash count uses `Crash ID`. Extra person rows do not increase it.
- Severity comes from the leading K, A, B, or C on `Crash Severity`.
- Contributing factors come from the combined `Contributing Factors` field, split on semicolons. `NONE`, `NO DATA`, and blank values are left out of the ranking. A crash with two factors counts once for each, so shares can exceed 100% together.
- Year and month come from `Crash Date`. The hour comes from `Crash Time`.
- County and road class are stored in uppercase.
- Latitude and longitude outside a broad Texas window are treated as missing. Those crashes stay in the counts and drop off the map only.
- Deaths are the sum of `Crash Death Count` after the crash-level collapse. That total is not the same thing as the number of fatal crashes.

The notebook walks through why those choices were made.

## Layout

```text
district_crashes.csv
        |
        v
scripts/process_data.py
        |
        v
data/processed/crashes.db
        |
        +--> app/api.py  -->  JSON
        |
        +--> static/       -->  the profile page
```

## Limitations

- Person, vehicle, and unit details are not exposed. The questions this version answers are about crashes.
- The file has no property-damage-only crashes, so these counts are not comparable to an all-crash rate.
- 2026 stops at the extract date, 22 October 2026. A lower 2026 total is not a full-year decline.
- `OTHER (EXPLAIN IN NARRATIVE)` is kept when it appears. It is a real code, and it is also a residual bucket.
- The map needs a network connection for the basemap tiles. The charts do not.
- Deployment to AWS is not in this version. The next step is to publish this same API on Lambda, behind a Lambda function URL, so the endpoint stays inside Lambda's always-free allowance.
