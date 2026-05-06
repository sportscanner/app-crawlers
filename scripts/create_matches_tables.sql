-- Run this SQL in your Postgres database to create the matches tables for the games/Splitwise feature.
-- Tracks logged sports matches, their players, scores, and Splitwise expense status.
--
-- Depends on: public.users (kinde_user_id column) must already exist.
--
-- Tables created:
--   public.match        — the match session itself
--   public.match_player — each participant in a match (by email, assigned to a team)
--   public.match_score  — per-game (set) scores within a match

-- ─── Enums ────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE public.matchtype AS ENUM ('SINGLES', 'DOUBLES');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public.matchstatus AS ENUM ('LOGGED', 'SPLIT');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ─── match ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.match (
    id                   UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by           VARCHAR        NOT NULL REFERENCES public.users(kinde_user_id),
    venue_name           VARCHAR        NOT NULL,
    sport                VARCHAR        NOT NULL,             -- 'badminton' | 'squash' | 'pickleball'
    match_type           public.matchtype NOT NULL,           -- SINGLES | DOUBLES
    played_at            TIMESTAMPTZ    NOT NULL,
    duration_minutes     INTEGER,                             -- NULL if not recorded
    winning_team         INTEGER,                             -- 1 or 2; NULL if draw / not determined
    total_cost           NUMERIC(10, 2),                      -- court booking cost in GBP; NULL until split
    status               public.matchstatus NOT NULL DEFAULT 'LOGGED',
    splitwise_expense_id VARCHAR,                             -- set on successful Splitwise call
    splitwise_error      VARCHAR,                             -- error category if Splitwise call failed
    created_at           TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.match IS 'A logged sports match session — created after playing';
COMMENT ON COLUMN public.match.status IS 'LOGGED = recorded, not yet split; SPLIT = Splitwise expense created';
COMMENT ON COLUMN public.match.splitwise_expense_id IS 'Splitwise expense ID; NULL until PATCH /matches/{id}/split is called';

-- ─── match_player ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.match_player (
    id                   UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id             UUID           NOT NULL REFERENCES public.match(id) ON DELETE CASCADE,
    email                VARCHAR        NOT NULL,             -- used for Splitwise expense debtors
    display_name         VARCHAR        NOT NULL,
    team                 INTEGER        NOT NULL,             -- 1 or 2
    is_creator           BOOLEAN        NOT NULL DEFAULT FALSE,
    splitwise_notified   BOOLEAN,                             -- NULL=not attempted, TRUE=notified, FALSE=unreachable email
    created_at           TIMESTAMPTZ    NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.match_player IS 'A participant in a match, identified by email and assigned to a team';
COMMENT ON COLUMN public.match_player.splitwise_notified IS 'Whether Splitwise successfully notified this player; NULL until split is triggered';

-- ─── match_score ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.match_score (
    id           UUID     PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id     UUID     NOT NULL REFERENCES public.match(id) ON DELETE CASCADE,
    game_number  INTEGER  NOT NULL,   -- 1-indexed: game 1, game 2, game 3...
    team1_score  INTEGER  NOT NULL,
    team2_score  INTEGER  NOT NULL
);

COMMENT ON TABLE public.match_score IS 'Score for one game (set) within a match';

-- ─── Indexes ──────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_match_created_by   ON public.match(created_by);
CREATE INDEX IF NOT EXISTS idx_match_sport        ON public.match(sport);
CREATE INDEX IF NOT EXISTS idx_match_status       ON public.match(status);
CREATE INDEX IF NOT EXISTS idx_match_player_match ON public.match_player(match_id);
CREATE INDEX IF NOT EXISTS idx_match_player_email ON public.match_player(email);
CREATE INDEX IF NOT EXISTS idx_match_score_match  ON public.match_score(match_id);

-- ─── Notes ────────────────────────────────────────────────────────────────────
--
-- When porting this feature to a new branch or environment:
--   1. Ensure public.users table exists (kinde_user_id VARCHAR primary key).
--   2. Run this script once per database (staging first, then production).
--   3. Set SPLITWISE_API_KEY in your .dev.env / production env vars.
--   4. SQLModel will call create_all() on startup — it will skip tables that
--      already exist, so running this script manually first is safe.
--   5. The enums (matchtype, matchstatus) are created with DO $$ BEGIN … EXCEPTION
--      WHEN duplicate_object THEN NULL so re-running the script is idempotent.
