-- Run this SQL in your Postgres database to create notifications tables.
-- Notifications are global messages; each user's acknowledgement is stored in notification_ack.

CREATE TABLE IF NOT EXISTS public.notification (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.notification_ack (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    notification_id UUID NOT NULL REFERENCES public.notification(id) ON DELETE CASCADE,
    acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, notification_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_ack_user_id ON public.notification_ack(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_active ON public.notification(active);

COMMENT ON TABLE public.notification IS 'Global notification messages shown to users';
COMMENT ON TABLE public.notification_ack IS 'Per-user acknowledgement (dismissal) of notifications';
