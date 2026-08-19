"""
ingest_v2.py
Bucket Chart CSV Loader
=======================================
Loads NBA shot data from the NBA_Shots_04_25 CSV dataset
into PostgreSQL via SQLAlcemy.
Filters to 2024-25 season only by default.

Source: https://github.com/DomSamangy/NBA_Shots_04_25

CSV columns used:
  SEASON_2       -> season         (e.g. "2024-25")
  TEAM_ID        -> team_id
  TEAM_NAME      -> teams.name
  PLAYER_ID      -> player_id
  PLAYER_NAME    -> players.full_name
  GAME_DATE      -> game_date      (format: MM-DD-YYYY)
  GAME_ID        -> game_id
  HOME_TEAM      -> games.home_team abbreviation
  AWAY_TEAM      -> games.away_team abbreviation
  EVENT_TYPE     -> shot_made      ("Made Shot" = True, "Missed Shot" = False)
  ACTION_TYPE    -> action_type
  SHOT_TYPE      -> shot_type
  BASIC_ZONE     -> shot_zone_basic
  ZONE_NAME      -> shot_zone_area
  ZONE_RANGE     -> shot_zone_range
  LOC_X          -> loc_x          (decimal feet)
  LOC_Y          -> loc_y          (decimal feet)
  SHOT_DISTANCE  -> shot_distance
  QUARTER        -> period
  MINS_LEFT      -> minutes_remaining
  SECS_LEFT      -> seconds_remaining

Usage:
  python ingest_v2.py

The DATABASE_URL environment variable must be set.
    Example: $env:DATABASE_URL = "postgresql://bucket_user:changeme_before_deploy@localhost:5432/bucket_chart"

Place NBA_2004_2025_Shots.csv in the same folder as this script.
"""

import os
import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, Column, Integer, Text, Boolean, Date, ForeignKey, Numeric
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nba_api.stats.static import teams as static_teams

# =============================================================================
# CONFIG
# =============================================================================

CSV_FILE     = "NBA_2004_2025_Shots.csv"
SEASON_TYPE  = "Regular Season"      # CSV only contains regular season data
CHUNK_SIZE   = 10_000                # rows to process at a time
DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# =============================================================================
# SQLALCHEMY MODELS
# Must match 01_schema.sql exactly
# =============================================================================

Base = declarative_base()


class Team(Base):
    __tablename__ = "teams"

    team_id      = Column(Integer, primary_key=True)
    name         = Column(Text, nullable=False)
    abbreviation = Column(Text, nullable=False)
    city         = Column(Text, nullable=False)
    state        = Column(Text)
    year_founded = Column(Integer)


class Player(Base):
    __tablename__ = "players"

    player_id  = Column(Integer, primary_key=True)
    first_name = Column(Text, nullable=False)
    last_name  = Column(Text, nullable=False)
    full_name  = Column(Text, nullable=False)
    is_active  = Column(Boolean, nullable=False, default=True)
    team_id    = Column(Integer, ForeignKey("teams.team_id"))


class Game(Base):
    __tablename__ = "games"

    game_id      = Column(Text, primary_key=True)
    game_date    = Column(Date, nullable=False)
    season       = Column(Text, nullable=False)
    season_type  = Column(Text, nullable=False)
    home_team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)


class Shot(Base):
    __tablename__ = "shots"

    shot_id           = Column(Integer, primary_key=True, autoincrement=True)
    player_id         = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    team_id           = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    game_id           = Column(Text, ForeignKey("games.game_id"), nullable=False)
    game_date         = Column(Date, nullable=False)
    season            = Column(Text, nullable=False)
    period            = Column(Integer, nullable=False)
    minutes_remaining = Column(Integer, nullable=False)
    seconds_remaining = Column(Integer, nullable=False)
    shot_made         = Column(Boolean, nullable=False)
    loc_x             = Column(Numeric(6, 2), nullable=False)
    loc_y             = Column(Numeric(6, 2), nullable=False)
    shot_distance     = Column(Integer, nullable=False)
    shot_type         = Column(Text, nullable=False)
    action_type       = Column(Text, nullable=False)
    shot_zone_basic   = Column(Text, nullable=False)
    shot_zone_area    = Column(Text, nullable=False)
    shot_zone_range   = Column(Text, nullable=False)
    game_event_id     = Column(Integer)             # not in CSV, will be NULL


# =============================================================================
# HELPERS
# =============================================================================

def get_seasons(first_season: int) -> list:
    """
    Enter the first season and generate a list of all seasons through the present
    """

    seasons = []

    for season in range(first_season, 2025, 1):
        seasons.append(str(season)+"-"+str((season+1)%100))

    return seasons



def upsert_teams(session: Session) -> dict:
    """
    Load all 30 NBA teams from nba_api static list.
    Returns abbreviation -> team_id mapping for use in game loading.
    """
    log.info("Upserting teams...")
    all_teams = static_teams.get_teams()

    for t in all_teams:
        stmt = pg_insert(Team).values(
            team_id      = t["id"],
            name         = t["full_name"],
            abbreviation = t["abbreviation"],
            city         = t["city"],
            state        = t["state"],
            year_founded = t["year_founded"],
        ).on_conflict_do_nothing(index_elements=["team_id"])
        session.execute(stmt)

    session.commit()
    log.info(f"  {len(all_teams)} teams upserted.")

    return {t["abbreviation"]: t["id"] for t in all_teams}


def upsert_players_from_df(session: Session, df: pd.DataFrame) -> None:
    """
    Upsert all unique players found in the dataframe.
    Splits PLAYER_NAME into first/last on the first space.
    """
    log.info("Upserting players...")
    unique_players = df[["PLAYER_ID", "PLAYER_NAME", "TEAM_ID"]].drop_duplicates("PLAYER_ID")

    for _, row in unique_players.iterrows():
        parts      = str(row["PLAYER_NAME"]).strip().split(" ", 1)
        first_name = parts[0]
        last_name  = parts[1] if len(parts) > 1 else ""
        team_id    = int(row["TEAM_ID"]) if pd.notna(row["TEAM_ID"]) else None

        stmt = pg_insert(Player).values(
            player_id  = int(row["PLAYER_ID"]),
            first_name = first_name,
            last_name  = last_name,
            full_name  = str(row["PLAYER_NAME"]),
            is_active  = True,
            team_id    = team_id,
        ).on_conflict_do_update(
            index_elements = ["player_id"],
            set_           = {
                "full_name": str(row["PLAYER_NAME"]),
                "is_active": True,
                "team_id":   team_id,
            }
        )
        session.execute(stmt)

    session.commit()
    log.info(f"  {len(unique_players)} players upserted.")


def upsert_games_from_df(
    session: Session,
    df: pd.DataFrame,
    abbr_to_id: dict,
) -> None:
    """
    Upsert all unique games found in the dataframe.
    Resolves HOME_TEAM/AWAY_TEAM abbreviations to team_ids.
    """
    log.info("Upserting games...")
    unique_games = df[["SEASON_2", "GAME_DATE", "GAME_ID", "HOME_TEAM", "AWAY_TEAM"]].drop_duplicates("GAME_ID")
    skipped = 0

    for _, row in unique_games.iterrows():
        home_team_id = abbr_to_id.get(str(row["HOME_TEAM"]))
        away_team_id = abbr_to_id.get(str(row["AWAY_TEAM"]))

        if not home_team_id or not away_team_id:
            log.warning(f"  Could not resolve teams for game {row['GAME_ID']} "
                        f"(HOME={row['HOME_TEAM']}, AWAY={row['AWAY_TEAM']}) — skipping.")
            skipped += 1
            continue

        # CSV date format is MM-DD-YYYY
        game_date = datetime.strptime(str(row["GAME_DATE"]), "%m-%d-%Y").date()

        stmt = pg_insert(Game).values(
            game_id      = str(row["GAME_ID"]),
            game_date    = game_date,
            season       = str(row["SEASON_2"]),
            season_type  = SEASON_TYPE,
            home_team_id = home_team_id,
            away_team_id = away_team_id,
        ).on_conflict_do_nothing(index_elements=["game_id"])
        session.execute(stmt)

    session.commit()
    log.info(f"  {len(unique_games) - skipped} games upserted, {skipped} skipped.")


def insert_shots_from_df(session: Session, df: pd.DataFrame) -> int:
    """
    Bulk insert all shots in the dataframe chunk.
    Skips duplicates via on_conflict_do_nothing.
    Returns number of rows processed.
    """
    shots = []

    for _, row in df.iterrows():
        game_date = datetime.strptime(str(row["GAME_DATE"]), "%m-%d-%Y").date()

        shots.append({
            "player_id":         int(row["PLAYER_ID"]),
            "team_id":           int(row["TEAM_ID"]),
            "game_id":           str(row["GAME_ID"]),
            "game_date":         game_date,
            "season":            str(row["SEASON_2"]),
            "period":            int(row["QUARTER"]),
            "minutes_remaining": int(row["MINS_LEFT"]),
            "seconds_remaining": int(row["SECS_LEFT"]),
            "shot_made":         str(row["SHOT_MADE"]).strip().upper() == "TRUE",
            "loc_x":             float(row["LOC_X"]),
            "loc_y":             float(row["LOC_Y"]),
            "shot_distance":     int(row["SHOT_DISTANCE"]),
            "shot_type":         str(row["SHOT_TYPE"]),
            "action_type":       str(row["ACTION_TYPE"]),
            "shot_zone_basic":   str(row["BASIC_ZONE"]),
            "shot_zone_area":    str(row["ZONE_NAME"]),
            "shot_zone_range":   str(row["ZONE_RANGE"]),
            "game_event_id":     None,   # not available in CSV
        })

    if shots:
        stmt = pg_insert(Shot).values(shots).on_conflict_do_nothing()
        session.execute(stmt)
        session.commit()

    return len(shots)


# =============================================================================
# MAIN
# =============================================================================

def main():
    seasons = get_seasons(2019)

    log.info("=" * 60)
    log.info(f"Bucket Chart CSV Loader — Seasons: {', '.join(seasons)}")
    log.info("=" * 60)

    # Confirm CSV exists
    if not os.path.exists(CSV_FILE):
        log.error(f"CSV file not found: {CSV_FILE}")
        log.error("Make sure NBA_2004_2025_Shots.csv is in the same folder as this script.")
        return

    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:

        # ── Stage 1: Teams ────────────────────────────────────────────────────
        abbr_to_id = upsert_teams(session)

        # ── Stage 2: Read CSV and filter to target season ─────────────────────
        log.info(f"Reading CSV and filtering to {', '.join(seasons)}...")
        df_full = pd.read_csv(CSV_FILE, low_memory=False)
        df = df_full[df_full["SEASON_2"].isin(seasons)].copy()
        log.info(f"  {len(df):,} rows found for {', '.join(seasons)} "
                 f"(out of {len(df_full):,} total rows).")

        if df.empty:
            log.error(f"No rows found for seasons {', '.join(seasons)}. Check the seasons submitted.")
            return

        # ── Stage 3: Players ──────────────────────────────────────────────────
        upsert_players_from_df(session, df)

        # ── Stage 4: Games ────────────────────────────────────────────────────
        upsert_games_from_df(session, df, abbr_to_id)

        # ── Stage 5: Shots (chunked) ──────────────────────────────────────────
        log.info(f"Inserting shots in chunks of {CHUNK_SIZE:,}...")
        total_shots = 0
        chunks = [df.iloc[i:i + CHUNK_SIZE] for i in range(0, len(df), CHUNK_SIZE)]

        for i, chunk in enumerate(chunks, start=1):
            count = insert_shots_from_df(session, chunk)
            total_shots += count
            log.info(f"  Chunk {i}/{len(chunks)} — {total_shots:,} shots inserted so far.")

    log.info("=" * 60)
    log.info(f"Load complete. Total shots inserted: {total_shots:,}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
