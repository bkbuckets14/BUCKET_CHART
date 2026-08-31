"""
main.py — Bucket Chart API
===========================
FastAPI backend for the Bucket Chart shot chart application.

Endpoints:
  GET /                                — health check
  GET /teams                           — all 30 NBA teams for dropdown
  GET /teams/{team_id}/players?date_from=&date_to=
                                       — players who played for this team
                                         (optionally scoped to a date range)
  GET /players/search?name=            — player autocomplete search
  GET /shots?player_id=&team_id=&date_from=&date_to=
                                       — filtered shot data for chart rendering

player_id and team_id are both required on /shots — a chart is always scoped
to a specific player's shots while they played for a specific team. At least
one of date_from/date_to is required as well.
Returns only the fields needed for frontend rendering.
"""

import os
from datetime import date
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Text, Boolean, Date, ForeignKey, Numeric
from sqlalchemy.orm import declarative_base, Session

# =============================================================================
# CONFIG
# =============================================================================

DATABASE_URL = os.environ["DATABASE_URL"]
engine       = create_engine(DATABASE_URL)
Base         = declarative_base()

app = FastAPI(title="Bucket Chart API")

# Allow all origins during development — tighten this in production
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_methods     = ["GET"],
    allow_headers     = ["*"],
)

# =============================================================================
# SQLALCHEMY MODELS
# Read-only mirrors of the database schema
# =============================================================================

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
    game_event_id     = Column(Integer)


# =============================================================================
# PYDANTIC RESPONSE MODELS
# Define the shape of data returned by each endpoint
# =============================================================================

class TeamResponse(BaseModel):
    team_id:      int
    name:         str
    abbreviation: str
    city:         str

    class Config:
        from_attributes = True


class PlayerResponse(BaseModel):
    player_id: int
    full_name: str
    team_id:   Optional[int]

    class Config:
        from_attributes = True


class ShotResponse(BaseModel):
    loc_x:          float
    loc_y:          float
    shot_made:      bool
    shot_type:      str
    action_type:    str
    shot_zone_basic: str
    game_date:      date

    class Config:
        from_attributes = True


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
def health_check():
    """Basic health check — confirms the API is running."""
    return {"status": "ok", "message": "Bucket Chart API is running."}


@app.get("/teams", response_model=list[TeamResponse])
def get_teams():
    """
    Returns all 30 NBA teams sorted alphabetically by name.
    Used to populate the team dropdown in the UI.
    """
    with Session(engine) as session:
        teams = session.query(Team).order_by(Team.name).all()
        return teams


@app.get("/teams/{team_id}/players", response_model=list[PlayerResponse])
def get_team_players(
    team_id:   int,
    date_from: Optional[date] = Query(None, description="Only players with a shot on/after this date"),
    date_to:   Optional[date] = Query(None, description="Only players with a shot on/before this date"),
):
    """
    Returns players who have at least one recorded shot for this team,
    sorted by name. Used to populate the player dropdown once a team has
    been selected — driven by shot history (shots.team_id) rather than
    players.team_id, since the latter only reflects a player's current team.

    If date_from/date_to are given, only players with a shot for this team
    within that range are returned — supports the flow where a date range
    is picked before the team/player.

    Example: /teams/1610612738/players?date_from=2023-10-01&date_to=2024-06-30
             → players who played for the Celtics during the 2023-24 season
    """
    with Session(engine) as session:
        query = (
            session.query(Player)
            .join(Shot, Shot.player_id == Player.player_id)
            .filter(Shot.team_id == team_id)
        )
        if date_from:
            query = query.filter(Shot.game_date >= date_from)
        if date_to:
            query = query.filter(Shot.game_date <= date_to)

        players = query.distinct().order_by(Player.full_name).all()
        return players


@app.get("/players/search", response_model=list[PlayerResponse])
def search_players(
    name: str = Query(..., min_length=1, description="Player name search string")
):
    """
    Returns players whose name contains the search string (case-insensitive).
    Used for the player autocomplete input.

    Example: /players/search?name=tat  →  returns Jayson Tatum and others
    """
    with Session(engine) as session:
        players = (
            session.query(Player)
            .filter(Player.full_name.ilike(f"%{name}%"))
            .order_by(Player.full_name)
            .limit(10)       # cap at 10 results for autocomplete performance
            .all()
        )
        return players


@app.get("/shots", response_model=list[ShotResponse])
def get_shots(
    player_id:  int            = Query(..., description="Player ID (required)"),
    team_id:    int            = Query(..., description="Team ID the player was on for these shots (required)"),
    date_from:  Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to:    Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """
    Returns shot data for chart rendering, scoped to a specific player while
    they played for a specific team. player_id and team_id are both required —
    a chart is always for one player's shots taken as a member of one team.
    At least one of date_from/date_to is also required.

    Example: /shots?player_id=1628369&team_id=1610612738&date_from=2024-01-01&date_to=2024-04-01
    """
    if not (date_from or date_to):
        raise HTTPException(
            status_code=400,
            detail="A date range (date_from and/or date_to) is required.",
        )

    with Session(engine) as session:
        query = session.query(
            Shot.loc_x,
            Shot.loc_y,
            Shot.shot_made,
            Shot.shot_type,
            Shot.action_type,
            Shot.shot_zone_basic,
            Shot.game_date,
        ).filter(
            Shot.player_id == player_id,
            Shot.team_id == team_id,
        )

        if date_from:
            query = query.filter(Shot.game_date >= date_from)
        if date_to:
            query = query.filter(Shot.game_date <= date_to)

        results = query.all()

        # Convert to list of dicts for Pydantic serialization
        return [
            {
                "loc_x":           float(r.loc_x),
                "loc_y":           float(r.loc_y),
                "shot_made":       r.shot_made,
                "shot_type":       r.shot_type,
                "action_type":     r.action_type,
                "shot_zone_basic": r.shot_zone_basic,
                "game_date":       r.game_date,
            }
            for r in results
        ]
