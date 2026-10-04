"""
ingest_v2.py — Bucket Chart Data Ingestion
===========================================
Pulls NBA shot data from the NBA Stats API and
writes it to the PostgreSQL database via SQLAlchemy.

Run order:
  1. Teams      (static list from nba_api)
  2. Players    (LeagueDashPlayerStats — live, season-aware)
  3. Shots      (ShotChartDetail — one call per player per season type)

Usage:
  python ingest_v2.py

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
from nba_api.stats.endpoints import leaguedashplayerstats, shotchartdetail

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

# =============================================================================
# CONFIG
# =============================================================================

SEASONS = ["2024-25", "2025-26"]
SEASON_TYPES = ["Regular Season", "Playoffs"]

# The NBA API is rate-limited — always sleep between calls
# 1.0s is conservative but safe; lower at your own risk
API_DELAY = 2.0  # seconds between API calls

DATABASE_URL = os.environ["DATABASE_URL"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

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

API_TIMEOUT = 60

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


def upsert_teams(session: Session) -> None:
    """
    Load all 30 NBA teams from nba_api's static list and upsert into DB.
    Uses ON CONFLICT DO NOTHING so re-runs are safe.
    """
    log.info("Upserting teams...")
    all_teams = static_teams.get_teams()  # returns a list of dicts

    for t in all_teams:
        stmt = (
            pg_insert(Team)
            .values(
                team_id=t["id"],
                name=t["full_name"],
                abbreviation=t["abbreviation"],
                city=t["city"],
                state=t["state"],
                year_founded=t["year_founded"],
            )
            .on_conflict_do_nothing(index_elements=["team_id"])
        )
        session.execute(stmt)

    session.commit()
    log.info(f"  {len(all_teams)} teams upserted.")


def upsert_players(session: Session, season: str, season_types: list[str]) -> list[int]:
    """
    Pull all players who recorded stats in the given season via
    LeagueDashPlayerStats, across each of the given season types, and upsert
    them. Returns the union of player_ids for use in shot ingestion.

    CommonAllPlayers' IsOnlyCurrentSeason flag was tried first but turned out
    to be unreliable for this: set to 1, it silently drops most of a past
    season's players (its actual selection logic isn't documented anywhere
    and doesn't correspond to any rule we could pin down); set to 0, it
    ignores the season parameter entirely and returns every player in NBA
    history. LeagueDashPlayerStats returns exactly the players with recorded
    stats for a given season + season type, which is what we actually want.
    """
    log.info(f"Fetching players for {season}...")

    # player_id -> row; querying every season_type since a player can appear
    # in Playoffs stats without much Regular Season presence (e.g. a
    # trade-deadline signing) and we don't want to miss their shots.
    player_rows = {}

    for season_type in season_types:
        time.sleep(API_DELAY)

        response = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star=season_type,
            headers=NBA_HEADERS,
            timeout=API_TIMEOUT,
        )
        df = response.get_data_frames()[0]

        for _, row in df.iterrows():
            player_rows[int(row["PLAYER_ID"])] = row

    for player_id, row in player_rows.items():
        # Split full name into first/last (best effort)
        parts = str(row["PLAYER_NAME"]).strip().split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
        full_name = row["PLAYER_NAME"]
        team_id = int(row["TEAM_ID"]) if row["TEAM_ID"] else None

        # team_id of 0 means the player has no current team (free agent etc.)
        if team_id == 0:
            team_id = None

        stmt = (
            pg_insert(Player)
            .values(
                player_id=player_id,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                is_active=True,
                team_id=team_id,
            )
            .on_conflict_do_update(
                index_elements=["player_id"],
                set_={
                    "full_name": full_name,
                    "is_active": True,
                    "team_id": team_id,
                },
            )
        )
        session.execute(stmt)

    session.commit()
    log.info(f"  {len(player_rows)} players upserted.")
    return list(player_rows.keys())


def ingest_shots_for_player(
    session: Session,
    player_id: int,
    season: str,
    season_type: str,
) -> int:
    """
    Pull all shots for one player/season/season_type and write to DB.
    Returns the number of shots inserted.
    """
    time.sleep(API_DELAY)

    try:
        response = shotchartdetail.ShotChartDetail(
            player_id=player_id,
            team_id=0,  # 0 = all teams
            season_nullable=season,
            season_type_all_star=season_type,
            context_measure_simple="FGA",  # FGA = makes + misses
            headers=NBA_HEADERS,
            timeout=API_TIMEOUT,
        )
        df = response.get_data_frames()[0]
    except Exception as e:
        log.warning(f"    API error for player {player_id}: {e}")
        return 0

    if df.empty:
        return 0

    shots_to_insert = []

    # Collect unique games from this batch first
    games_seen = {}

    for _, row in df.iterrows():
        game_id = str(row["GAME_ID"])
        game_date = datetime.strptime(str(row["GAME_DATE"]), "%Y%m%d").date()

        if game_id not in games_seen:
            # HTM = home team abbreviation, VTM = visitor team abbreviation
            # We store team_ids, so we look them up from our teams table
            games_seen[game_id] = {
                "game_id": game_id,
                "game_date": game_date,
                "season": season,
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
                "season": season,
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
                    int(row["GAME_EVENT_ID"]) if row["GAME_EVENT_ID"] else None
                ),
            }
        )

    # Upsert games before shots (foreign key dependency)
    _upsert_games(session, games_seen, session)

    # Bulk insert shots — skip duplicates
    if shots_to_insert:
        stmt = (
            pg_insert(Shot)
            .values(shots_to_insert)
            .on_conflict_do_nothing(
                index_elements=["player_id", "game_id", "game_event_id"]
            )
        )
        session.execute(stmt)
        session.commit()

    return len(shots_to_insert)


def _upsert_games(session: Session, games_seen: dict, _) -> None:
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
    log.info("=" * 60)
    log.info(f"Bucket Chart Ingestion — Seasons: {', '.join(SEASONS)}")
    log.info("=" * 60)

    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:

        # ── Stage 1: Teams ────────────────────────────────────────────────────
        upsert_teams(session)

        total_shots = 0

        for season in SEASONS:
            log.info("-" * 60)
            log.info(f"Season: {season}")

            # ── Stage 2: Players ─────────────────────────────────────────────
            # Rosters differ per season, so players are fetched fresh each time.
            player_ids = upsert_players(session, season, SEASON_TYPES)

            # ── Stage 3: Shots ───────────────────────────────────────────────
            total_players = len(player_ids)

            for i, player_id in enumerate(player_ids, start=1):
                for season_type in SEASON_TYPES:
                    log.info(
                        f"  [{i}/{total_players}] Player {player_id} "
                        f"— {season} {season_type}"
                    )
                    count = ingest_shots_for_player(
                        session, player_id, season, season_type
                    )
                    total_shots += count
                    if count:
                        log.info(f"    {count} shots inserted.")

    log.info("=" * 60)
    log.info(f"Ingestion complete. Total shots inserted: {total_shots}")
    log.info("=" * 60)

    with open("date_of_last_run.txt", "w") as f:
        f.write(datetime.now().date().isoformat())


if __name__ == "__main__":
    main()
