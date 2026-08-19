-- =============================================================================
-- BUCKET CHART — Database Schema
-- Runs automatically on first container boot via docker-entrypoint-initdb.d
-- =============================================================================

-- -----------------------------------------------------------------------------
-- TEAMS
-- Populated once from nba_api's static teams list
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    team_id         INTEGER PRIMARY KEY,    -- NBA's own team ID (e.g. 1610612738)
    name            TEXT NOT NULL,          -- e.g. "Boston Celtics"
    abbreviation    TEXT NOT NULL,          -- e.g. "BOS"
    city            TEXT NOT NULL,
    state           TEXT,
    year_founded    INTEGER
);

-- -----------------------------------------------------------------------------
-- PLAYERS
-- Populated once from nba_api's static players list, updated each season
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS players (
    player_id       INTEGER PRIMARY KEY,    -- NBA's own player ID (e.g. 1628369)
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    full_name       TEXT NOT NULL,          -- denormalized for easy querying (e.g. Jayson Tatum)
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    team_id         INTEGER REFERENCES teams(team_id)
);

-- -----------------------------------------------------------------------------
-- GAMES
-- One row per game; populated alongside shots
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS games (
    game_id         TEXT PRIMARY KEY,       -- NBA's game ID string (e.g. "0022300001")
    game_date       DATE NOT NULL,
    season          TEXT NOT NULL,          -- e.g. "2024-25"
    season_type     TEXT NOT NULL,          -- "Regular Season", "Playoffs", etc.
    home_team_id    INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id    INTEGER NOT NULL REFERENCES teams(team_id)
);

CREATE INDEX IF NOT EXISTS idx_games_date      ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_games_season    ON games(season);

-- -----------------------------------------------------------------------------
-- SHOTS
-- Core table — one row per shot attempt
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shots (
    shot_id             SERIAL PRIMARY KEY,
    -- Who & when
    player_id           INTEGER NOT NULL REFERENCES players(player_id),
    team_id             INTEGER NOT NULL REFERENCES teams(team_id),
    game_id             TEXT    NOT NULL REFERENCES games(game_id),
    game_date           DATE    NOT NULL,   -- denormalized for faster filtering
    season              TEXT    NOT NULL,   -- denormalized for faster filtering
    -- Game clock
    period              INTEGER NOT NULL,   -- 1–4 regulation, 5+ OT
    minutes_remaining   INTEGER NOT NULL,
    seconds_remaining   INTEGER NOT NULL,
    -- Result
    shot_made           BOOLEAN NOT NULL,   -- TRUE = make, FALSE = miss
    -- Location
    loc_x               NUMERIC(6,2) NOT NULL,   -- feet from the basket, left/right (decimal)
    loc_y               NUMERIC(6,2) NOT NULL,   -- feet from the baseline (decimal)
    shot_distance       INTEGER NOT NULL,   -- feet from basket
    -- Shot classification
    shot_type           TEXT NOT NULL,      -- "2PT Field Goal" or "3PT Field Goal"
    action_type         TEXT NOT NULL,      -- "Jump Shot", "Layup", "Dunk", etc.
    shot_zone_basic     TEXT NOT NULL,      -- "Mid-Range", "Restricted Area", etc.
    shot_zone_area      TEXT NOT NULL,      -- "Left Side", "Center", "Right Side", etc.
    shot_zone_range     TEXT NOT NULL,      -- "Less Than 8 ft", "8-16 ft", etc.
    -- Metadata
    game_event_id       INTEGER             -- NBA's event ID within the game
);

-- Indexes for the filters your UI will use most
CREATE INDEX IF NOT EXISTS idx_shots_player     ON shots(player_id);
CREATE INDEX IF NOT EXISTS idx_shots_team       ON shots(team_id);
CREATE INDEX IF NOT EXISTS idx_shots_game       ON shots(game_id);
CREATE INDEX IF NOT EXISTS idx_shots_date       ON shots(game_date);
CREATE INDEX IF NOT EXISTS idx_shots_season     ON shots(season);
CREATE INDEX IF NOT EXISTS idx_shots_made       ON shots(shot_made);
CREATE INDEX IF NOT EXISTS idx_shots_type       ON shots(shot_type);
CREATE INDEX IF NOT EXISTS idx_shots_zone       ON shots(shot_zone_basic);

-- Composite index for the most common query pattern: player + season
CREATE INDEX IF NOT EXISTS idx_shots_player_season ON shots(player_id, season);
CREATE INDEX IF NOT EXISTS idx_shots_team_season   ON shots(team_id, season);
