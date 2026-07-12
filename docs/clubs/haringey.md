# Haringey Council

2 venues, `https://haringey.gov.uk/`. Badminton.
Code: `sportscanner/crawlers/parsers/haringey/`.

## API shape

Base: `https://flow.onl/api/activities/venue/{venue_slug}/activity/badminton/v2/times?date=YYYY-MM-DD`

Same `flow.onl` Gladstone white-label platform as Active Lambeth (see
[active-lambeth.md](active-lambeth.md) and [better-gll.md](better-gll.md) for the
shared mechanics) — a **different** deployment on the same domain, not the same
tenant. Reuses `BetterLeisureResponseParserStrategy` / `BetterStyleCrawler`.

Headers: `origin: https://haringeyactivewellbeing.bookings.flow.onl`, referer set
to that site's root (not a per-activity path like the other Gladstone-family
providers use), desktop Chrome `user-agent`.

## Activity slugs

Only one activity, no 40/60min split: `badminton/v2`. Unlike Active Lambeth on
the same `flow.onl` platform, this deployment **is** on `/v2` — reinforcing that
the v1/v2 state is per-deployment (even per-tenant on the same domain), not
something you can infer from one Gladstone-family provider to another. Always
verify directly against the specific venue/tenant.

## Status (July 2026)

Confirmed live: both venues return data. No known issues.
