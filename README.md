# Bucket Chart

An NBA shot-chart visualization app. Pick a team, a player, and a date range, and see their made/missed shots plotted on a half-court diagram.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + Vite, plain JS/JSX, `d3` (scales only) + `axios` |
| API | Python 3.12, FastAPI + SQLAlchemy 2.0 + Pydantic |
| Database | PostgreSQL 16 |
| Ingestion | Python scripts — live NBA Stats API scraper, and a bulk CSV loader |
| Orchestration | Docker Compose |
| Formatting | Black (Python), Prettier (JS/CSS), oxlint (JS lint) |

## Project structure

```
BUCKET_CHART/
├── api/            FastAPI backend (main.py)
├── db/init/        Postgres schema, run automatically on first container boot
├── ingestion/       Scripts that populate the database with shot data
├── frontend/        React + Vite UI
└── docker-compose.yml
```

## Getting started

**Prerequisites:** Docker Desktop.

1. Clone the repo and copy the example env file:
   ```
   cp .env.example .env
   ```
   The defaults work for local development as-is.

2. Start the database, API, and frontend:
   ```
   docker compose up -d db api frontend
   ```
   (Add `pgadmin` to that list if you want a DB browser at [http://localhost:5050](http://localhost:5050).)

3. Load shot data — see [Loading data](#loading-data) below, since the database starts empty.

4. Open the app: [http://localhost:5173](http://localhost:5173)
   The API is also directly browsable at [http://localhost:8000/docs](http://localhost:8000/docs).

5. When done:
   ```
   docker compose down
   ```
   This keeps the `bucket_chart_postgres_data` volume, so loaded data persists between sessions.

## Loading data

The `ingestion/` service populates `teams`, `players`, `games`, and `shots`. There are two ways to load data — pick one:

- **Bulk CSV load (`ingest_v2.py`, the default `docker-compose` ingestion command)** — loads historical shot data from the [DomSamangy/NBA_Shots_04_25](https://github.com/DomSamangy/NBA_Shots_04_25) dataset. Download `NBA_2004_2025_Shots.csv` from that source and place it in `ingestion/` (it's gitignored — not included in this repo, it's roughly 865 MB) before running:
  ```
  docker compose up ingestion
  ```
  By default this loads seasons 2019–20 through 2024–25 — see the `get_seasons(2019)` call in `main()` within `ingestion/ingest_v2.py` to change the range.

- **Live NBA Stats API scrape (`ingest.py`)** — pulls the current season directly from `stats.nba.com` via [`nba_api`](https://github.com/swar/nba_api), no CSV required, but rate-limited and slower:
  ```
  docker compose run --rm ingestion python ingest.py
  ```

  *Note:* The NBA Stats API can be finicky and requests often time-out. This is why the CSV file is used as the primary ingestion source in the Docker Compose file, even though it is only up-tp-date through the 2024-25 season.

## API reference

All endpoints are `GET`. Full interactive docs at `/docs` once the API is running.

| Endpoint | Description |
|---|---|
| `/teams` | All 30 NBA teams |
| `/teams/{team_id}/players?date_from=&date_to=` | Players who played for this team, optionally scoped to a date range |
| `/shots?player_id=&team_id=&date_from=&date_to=` | Shot data for one player on one team. `player_id`/`team_id` are required; at least one of `date_from`/`date_to` is required |

## Development

**Frontend** (`frontend/`):
```
npm run dev            # start Vite dev server directly (outside Docker)
npm run lint            # oxlint
npm run format           # prettier --write .
npm run format:check      # prettier --check .
```

**Python** (repo root):
```
pip install -r requirements-dev.txt
black .                   # format api/ and ingestion/
```
