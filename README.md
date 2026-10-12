# Bucket Chart

An NBA shot-chart visualization app. Pick a team, a player, and a date range, and see their made/missed shots plotted on a half-court diagram.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + Vite, plain JS/JSX, `d3` (scales only) + `axios` |
| API | Python 3.12, FastAPI + SQLAlchemy 2.0 + Pydantic |
| Database | PostgreSQL 16 |
| Ingestion | Python scripts — live NBA Stats API scraper (current method) or bulk csv load (old method) |
| Orchestration | Docker Compose |

## Project structure

```
BUCKET_CHART/
├── api/                  FastAPI backend (main.py)
├── db/init/              Postgres schema (01_schema.sql), run automatically on first container boot
├── ingestion/            Scripts that populate the database with shot data
│   ├── ingest_v2.py        One-time backfill from the NBA Stats API
│   ├── ingest_update.py    Daily in-season update (container default)
│   └── ingest.py           Legacy bulk CSV load
├── frontend/             React + Vite UI
├── docker-compose.yml
└── .env.example          Template for .env
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

3. Run the one-time backfill, since the database starts empty:
   ```
   docker compose run --rm ingestion python ingest_v2.py
   ```
   This scrapes every player's shots for the configured seasons, so expect it to take a few hours. See [Loading data](#loading-data) for details.

4. Open the app: [http://localhost:5173](http://localhost:5173)
   The API is also directly browsable at [http://localhost:8000/docs](http://localhost:8000/docs).

5. During the season, pull in new games with the daily update (or [schedule it](#scheduling-the-daily-update)):
   ```
   docker compose run --rm ingestion
   ```

6. When done:
   ```
   docker compose down
   ```
   This keeps the `bucket_chart_postgres_data` volume, so loaded data persists between sessions.

## Loading data

The `ingestion/` service populates `teams`, `players`, `games`, and `shots` from `stats.nba.com` via [`nba_api`](https://github.com/swar/nba_api). Loading works in two stages: a one-time backfill, then a daily update that adds only new games.

### 1. Backfill (`ingest_v2.py`)

Loads all teams, then every player who recorded stats in each season listed in `SEASONS` (currently `2024-25` and `2025-26`), then each player's shots for the Regular Season and Playoffs:
```
docker compose run --rm ingestion python ingest_v2.py
```
It makes one API call per player per season type, with a 2-second delay between calls (`API_DELAY`), so a full run takes a few hours. Re-running it is safe: duplicate shots are skipped via the `(player_id, game_id, game_event_id)` unique key.

When it finishes, it writes today's date to `ingestion/date_of_last_run.txt`. The daily update starts from that date.

### 2. Daily update (`ingest_update.py`)

This is the ingestion container's default command. It fetches every shot league-wide from the last run date through today for the current `SEASON` (currently `2026-27`), looks up any players it hasn't seen before, and inserts the new games and shots:
```
docker compose run --rm ingestion
```
If any API call fails, `date_of_last_run.txt` is left unchanged, so the next run retries the same window. Shots that did get inserted are skipped as duplicates on the retry.

A few things to know:
- `date_of_last_run.txt` must exist before the first update, so run the backfill first. It's gitignored, so each machine keeps its own copy.
- The update only covers `SEASON`. At the start of each new season, bump `SEASON` in `ingestion/ingest_update.py` (and add the season that just ended to `SEASONS` in `ingest_v2.py` if you want it covered by future backfills).
- During the offseason the update simply finds no new shots.

### Alternative: bulk CSV load (`ingest.py`, legacy)

Loads historical shot data from the [DomSamangy/NBA_Shots_04_25](https://github.com/DomSamangy/NBA_Shots_04_25) dataset instead of scraping. Download `NBA_2004_2025_Shots.csv` from that source and place it in `ingestion/` (it's roughly 865 MB and isn't included in this repo) before running:
```
docker compose run --rm ingestion python ingest.py
```
By default this loads seasons 2023-24 through 2024-25. To change the range, see the `FIRST_SEASON` global variable and the `get_seasons(FIRST_SEASON)` call in `main()` within `ingestion/ingest.py`. Note two caveats:
- This dataset doesn't include `game_event_id`, so re-running it against already-loaded data will duplicate shots (see the comment in `insert_shots_from_df`).
- It doesn't write `date_of_last_run.txt`. To follow it with daily updates, create that file yourself with a start date in `MM/DD/YYYY` format.

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
```
