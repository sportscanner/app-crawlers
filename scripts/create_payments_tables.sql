-- Run this SQL in your Postgres database to create the Stripe Connect + Games
-- payments tables. Lets organizers connect a Stripe Express account, create
-- upcoming games, and have joining users pay in directly to the organizer's
-- connected account (minus a platform fee).
--
-- Depends on: public.users (kinde_user_id column) must already exist.
--
-- Tables created:
--   public.stripe_connected_account — one row per user onboarded as a payee
--   public.game                     — an upcoming, joinable game session
--   public.game_participant         — a user who paid to join a game

-- ─── Enums ────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE public.gamestatus AS ENUM ('OPEN', 'FULL', 'CANCELLED', 'COMPLETED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public.gameparticipantstatus AS ENUM ('PENDING', 'PAID', 'REFUNDED', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ─── stripe_connected_account ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.stripe_connected_account (
    kinde_user_id       VARCHAR        PRIMARY KEY REFERENCES public.users(kinde_user_id),
    stripe_account_id   VARCHAR        NOT NULL,
    details_submitted   BOOLEAN        NOT NULL DEFAULT FALSE,
    charges_enabled     BOOLEAN        NOT NULL DEFAULT FALSE,
    payouts_enabled     BOOLEAN        NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ    NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.stripe_connected_account IS 'Stripe Express account per user, onboarded to receive Games payouts';
COMMENT ON COLUMN public.stripe_connected_account.charges_enabled IS 'Kept in sync via the account.updated webhook; gates creating a paid Game';

-- ─── game ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.game (
    id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organizer_id             VARCHAR     NOT NULL REFERENCES public.users(kinde_user_id),
    venue_name               VARCHAR     NOT NULL,
    sport                    VARCHAR     NOT NULL,             -- 'badminton' | 'squash' | 'pickleball' | 'padel'
    scheduled_at             TIMESTAMPTZ NOT NULL,
    duration_minutes         INTEGER,
    capacity                 INTEGER     NOT NULL,             -- max paid participants (organizer not counted)
    price_pence              INTEGER     NOT NULL,             -- amount each joining participant pays
    currency                 VARCHAR     NOT NULL DEFAULT 'gbp',
    platform_fee_percent     DOUBLE PRECISION NOT NULL,        -- snapshot at creation time
    platform_fee_fixed_pence INTEGER     NOT NULL,             -- snapshot at creation time
    status                   public.gamestatus NOT NULL DEFAULT 'OPEN',
    notes                    VARCHAR,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.game IS 'An upcoming, joinable game session — payment happens upfront on join, routed to the organizer';
COMMENT ON COLUMN public.game.price_pence IS 'Integer minor-unit amount (pence), matching Stripe''s own convention — avoids float/Decimal rounding drift';

-- ─── game_participant ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.game_participant (
    id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id                  UUID        NOT NULL REFERENCES public.game(id) ON DELETE CASCADE,
    user_id                  VARCHAR     NOT NULL REFERENCES public.users(kinde_user_id),
    status                   public.gameparticipantstatus NOT NULL DEFAULT 'PENDING',
    stripe_payment_intent_id VARCHAR     NOT NULL,
    amount_pence             INTEGER     NOT NULL,
    platform_fee_pence       INTEGER     NOT NULL,
    joined_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.game_participant IS 'A user who paid (or is paying) to join a Game; status is updated by the Stripe webhook';

-- ─── Indexes ──────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_stripe_connected_account_stripe_id ON public.stripe_connected_account(stripe_account_id);
CREATE INDEX IF NOT EXISTS idx_game_organizer                     ON public.game(organizer_id);
CREATE INDEX IF NOT EXISTS idx_game_status                        ON public.game(status);
CREATE INDEX IF NOT EXISTS idx_game_scheduled_at                  ON public.game(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_game_participant_game               ON public.game_participant(game_id);
CREATE INDEX IF NOT EXISTS idx_game_participant_user               ON public.game_participant(user_id);
CREATE INDEX IF NOT EXISTS idx_game_participant_payment_intent      ON public.game_participant(stripe_payment_intent_id);

-- ─── Notes ────────────────────────────────────────────────────────────────────
--
-- When porting this feature to a new branch or environment:
--   1. Ensure public.users table exists (kinde_user_id VARCHAR primary key).
--   2. Run this script once per database (staging first, then production).
--   3. Set STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET in your .dev.env / production env vars.
--   4. Configure a Stripe webhook (test mode first) pointed at
--      POST {API_BASE_URL}/payments/webhook, subscribed to at least:
--      account.updated, payment_intent.succeeded, payment_intent.payment_failed, charge.refunded.
--   5. SQLModel will call create_all() on startup — it will skip tables that
--      already exist, so running this script manually first is safe.
--   6. The enums (gamestatus, gameparticipantstatus) are created with
--      DO $$ BEGIN … EXCEPTION WHEN duplicate_object THEN NULL so re-running
--      the script is idempotent.
