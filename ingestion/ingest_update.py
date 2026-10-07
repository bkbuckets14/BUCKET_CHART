"""
ingest_update.py — Bucket Chart Data Ingestion
===========================================
Pulls NBA shot data from the NBA Stats API and
writes it to the PostgreSQL database via SQLAlchemy.

Usage:
  python ingest_update.py

The DATABASE_URL environment variable must be set (handled by docker-compose).
"""

import os
import time
import logging
from datetime import datetime
import pandas as pd

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Text,
    Boolean,
    Date,
    ForeignKey,
    BigInteger,
)
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

import nba_api.library.http as nba_http
from curl_cffi import requests as curl_requests
from nba_api.stats.static import teams as static_teams
from nba_api.stats.endpoints import shotchartdetail, commonplayerinfo


# =============================================================================
# CONFIG
# =============================================================================

DATABASE_URL = os.environ["DATABASE_URL"]

SEASON = "2026-27"
# Playoffs returns no rows during the regular season, so it's safe to always
# query both
SEASON_TYPES = ["Regular Season", "Playoffs"]

# The NBA API is rate-limited — always sleep between calls
# 1.0s is conservative but safe; lower at your own risk
API_DELAY = 2.0  # seconds between API calls

API_TIMEOUT = 60

# Postgres caps a statement at 65,535 bind parameters; Shot rows use 18 each,
# so ~3,600 rows is the hard ceiling. 1,000 leaves plenty of headroom.
SHOT_BATCH_SIZE = 1000

NBA_HEADERS = {
    "Host": "stats.nba.com",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

# stats.nba.com sits behind Akamai bot detection that fingerprints the TLS
# handshake itself: plain `requests`/urllib3 connections get their TLS
# ClientHello accepted but the HTTP response is silently withheld, which
# surfaces as a read timeout no matter what headers are sent. curl_cffi
# reproduces a real Chrome TLS fingerprint, which Akamai lets through.
# nba_api's HTTP layer calls `requests.get(...)` directly (see
# nba_api/library/http.py), so we replace that one call site.


def _disguised_get(url=None, params=None, headers=None, proxies=None, timeout=None):
    return curl_requests.get(
        url,
        params=params,
        headers=headers,
        proxies=proxies,
        timeout=timeout,
        impersonate="chrome",
    )


nba_http.requests.get = _disguised_get

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# =============================================================================
# SQLALCHEMY MODELS
# Mirror the schema in 01_schema.sql — column names must match exactly
# =============================================================================

Base = declarative_base()


class Team(Base):
    __tablename__ = "teams"

    team_id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    abbreviation = Column(Text, nullable=False)
    city = Column(Text, nullable=False)
    state = Column(Text)
    year_founded = Column(Integer)


class Player(Base):
    __tablename__ = "players"

    player_id = Column(Integer, primary_key=True)
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    full_name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    team_id = Column(Integer, ForeignKey("teams.team_id"))


class Game(Base):
    __tablename__ = "games"

    game_id = Column(Text, primary_key=True)
    game_date = Column(Date, nullable=False)
    season = Column(Text, nullable=False)
    season_type = Column(Text, nullable=False)
    home_team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)


class Shot(Base):
    __tablename__ = "shots"

    shot_id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    game_id = Column(Text, ForeignKey("games.game_id"), nullable=False)
    game_date = Column(Date, nullable=False)
    season = Column(Text, nullable=False)
    period = Column(Integer, nullable=False)
    minutes_remaining = Column(Integer, nullable=False)
    seconds_remaining = Column(Integer, nullable=False)
    shot_made = Column(Boolean, nullable=False)
    loc_x = Column(Integer, nullable=False)
    loc_y = Column(Integer, nullable=False)
    shot_distance = Column(Integer, nullable=False)
    shot_type = Column(Text, nullable=False)
    action_type = Column(Text, nullable=False)
    shot_zone_basic = Column(Text, nullable=False)
    shot_zone_area = Column(Text, nullable=False)
    shot_zone_range = Column(Text, nullable=False)
    game_event_id = Column(Integer)


# =============================================================================
# HELPERS
# =============================================================================

def get_date_of_last_run() -> str:
    '''
    Gets the date of the last run from the file, so ingestion update knows where to start.
    '''
    with open("date_of_last_run.txt", "r") as f:
        return f.read().strip()

def single_player_call(player_id: int) -> dict:

    time.sleep(API_DELAY)

    response = commonplayerinfo.CommonPlayerInfo(
        player_id=player_id,
        headers=NBA_HEADERS,
        timeout=API_TIMEOUT,
    )

    player_data = response.get_data_frames()[0].iloc[0].to_dict()

    # Cast numpy types to plain Python — psycopg2 can't adapt numpy.int64
    insert_data = {
        "player_id": int(player_data["PERSON_ID"]),
        "first_name": str(player_data["FIRST_NAME"]),
        "last_name": str(player_data["LAST_NAME"]),
        "full_name": str(player_data["DISPLAY_FIRST_LAST"]),
        "is_active": True,
        "team_id": int(player_data["TEAM_ID"]) or None,  # 0 = no team
    }

    return insert_data


def insert_shots(
    session: Session, start_date: str, end_date: str, season_type: str
) -> int | None:
    """
    Returns the number of shots inserted, or None if the shot chart API call
    failed (so main() knows not to advance the last-run date).
    """

    time.sleep(API_DELAY)
    
    try:
        response = shotchartdetail.ShotChartDetail(
            player_id=0, #0 = all players
            team_id=0,  # 0 = all teams
            season_nullable=SEASON,
            season_type_all_star=season_type,
            context_measure_simple="FGA",  # FGA = makes + misses
            date_from_nullable=start_date,
            date_to_nullable=end_date,
            headers=NBA_HEADERS,
            timeout=API_TIMEOUT,
        )
        df = response.get_data_frames()[0]
    except Exception as e:
        log.warning(f"    API error: {e}")
        return None

    if df.empty:
        return 0

    shots_to_insert = []

    # Collect unique games and players from this patch
    games_seen = {}
    players_seen = {}

    # Only look up players we don't already have — one API call per player
    shot_player_ids = {int(pid) for pid in df["PLAYER_ID"].unique()}
    known_player_ids = {
        pid
        for (pid,) in session.query(Player.player_id).filter(
            Player.player_id.in_(shot_player_ids)
        )
    }

    failed_player_ids = set()
    for player_id in shot_player_ids - known_player_ids:
        try:
            players_seen[player_id] = single_player_call(player_id)
        except Exception as e:
            log.warning(f"    Player lookup failed for {player_id}: {e} — skipping their shots.")
            failed_player_ids.add(player_id)

    log.info(f" Number of Failed Player Ids: {len(failed_player_ids)} ")
    
    for _, row in df.iterrows():
        player_id = int(row["PLAYER_ID"])

        # No player row means the shot would violate the foreign key
        if player_id in failed_player_ids:
            continue

        game_id = str(row["GAME_ID"])
        game_date = datetime.strptime(str(row["GAME_DATE"]), "%Y%m%d").date()

        if game_id not in games_seen:
            # HTM = home team abbreviation, VTM = visitor team abbreviation
            # We store team_ids, so we look them up from our teams table
            games_seen[game_id] = {
                "game_id": game_id,
                "game_date": game_date,
                "season": SEASON,
                "season_type": season_type,
                "htm": row["HTM"],  # home team abbreviation
                "vtm": row["VTM"],  # visitor team abbreviation
            }

        shots_to_insert.append(
            {
                "player_id": int(row["PLAYER_ID"]),
                "team_id": int(row["TEAM_ID"]),
                "game_id": game_id,
                "game_date": game_date,
                "season": SEASON,
                "period": int(row["PERIOD"]),
                "minutes_remaining": int(row["MINUTES_REMAINING"]),
                "seconds_remaining": int(row["SECONDS_REMAINING"]),
                "shot_made": bool(row["SHOT_MADE_FLAG"]),
                "loc_x": int(row["LOC_X"]),
                "loc_y": int(row["LOC_Y"]),
                "shot_distance": int(row["SHOT_DISTANCE"]),
                "shot_type": str(row["SHOT_TYPE"]),
                "action_type": str(row["ACTION_TYPE"]),
                "shot_zone_basic": str(row["SHOT_ZONE_BASIC"]),
                "shot_zone_area": str(row["SHOT_ZONE_AREA"]),
                "shot_zone_range": str(row["SHOT_ZONE_RANGE"]),
                "game_event_id": (
                    int(row["GAME_EVENT_ID"]) if pd.notna(row["GAME_EVENT_ID"]) else None
                ),
            }
        )

    # Upsert players before shots (foreign key dependency)
    _upsert_players(session, players_seen)

    # Upsert games before shots (foreign key dependency)
    _upsert_games(session, games_seen)

    # Bulk insert shots in batches — skip duplicates
    inserted = 0
    for i in range(0, len(shots_to_insert), SHOT_BATCH_SIZE):
        batch = shots_to_insert[i : i + SHOT_BATCH_SIZE]
        stmt = (
            pg_insert(Shot)
            .values(batch)
            .on_conflict_do_nothing(
                index_elements=["player_id", "game_id", "game_event_id"]
            )
        )
        inserted += session.execute(stmt).rowcount
    session.commit()

    return inserted

def _upsert_players(session: Session, players_seen: dict) -> None:
    """
    Upsert player rows.
    """
    player_data = list(players_seen.values())

    # Bulk insert or update players
    if player_data:
        stmt = pg_insert(Player).values(player_data)
        # stmt.excluded refers to each row's own proposed values
        stmt = stmt.on_conflict_do_update(
            index_elements=["player_id"],
            set_={
                "full_name": stmt.excluded.full_name,
                "is_active": True,
                "team_id": stmt.excluded.team_id,
            },
        )
        session.execute(stmt)
        session.commit()

def _upsert_games(session: Session, games_seen: dict) -> None:
    """
    Upsert game rows. We resolve HTM/VTM abbreviations to team_ids here.
    """
    # Build abbreviation -> team_id map from DB
    teams = session.query(Team).all()
    abbr_to_id = {t.abbreviation: t.team_id for t in teams}

    for game_id, g in games_seen.items():
        home_team_id = abbr_to_id.get(g["htm"])
        away_team_id = abbr_to_id.get(g["vtm"])

        if not home_team_id or not away_team_id:
            log.warning(
                f"    Could not resolve team IDs for game {game_id} "
                f"(HTM={g['htm']}, VTM={g['vtm']}) — skipping game row."
            )
            continue

        stmt = (
            pg_insert(Game)
            .values(
                game_id=game_id,
                game_date=g["game_date"],
                season=g["season"],
                season_type=g["season_type"],
                home_team_id=home_team_id,
                away_team_id=away_team_id,
            )
            .on_conflict_do_nothing(index_elements=["game_id"])
        )
        session.execute(stmt)

    session.commit()


# =============================================================================
# MAIN
# =============================================================================


def main():
    start_date = get_date_of_last_run()
    end_date = datetime.now().strftime("%m/%d/%Y")


    log.info("=" * 60)
    log.info(f"Bucket Chart Ingestion — Starting from {start_date}")
    log.info("=" * 60)

    engine = create_engine(DATABASE_URL)

    total_shots = 0
    failed = False

    with Session(engine) as session:
        for season_type in SEASON_TYPES:
            log.info(f"Season type: {season_type}")
            count = insert_shots(session, start_date, end_date, season_type)
            if count is None:
                failed = True
                continue
            total_shots += count
            log.info(f"    {count} shots inserted.")

    # Don't advance the last-run date if any API call failed, or the next
    # run would skip this window entirely. Shots that did make it in are
    # skipped as duplicates on the retry.
    if failed:
        log.error("Ingestion failed — date_of_last_run.txt left unchanged.")
        return

    log.info("=" * 60)
    log.info(f"Ingestion complete. Total shots inserted: {total_shots}")
    log.info("=" * 60)

    with open("date_of_last_run.txt", "w") as f:
        f.write(end_date)


if __name__ == "__main__":
    main()
