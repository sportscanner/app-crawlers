# Better / GLL (Greenwich Leisure Limited)

35 venues, `https://www.better.org.uk`. Badminton, squash, pickleball.
Code: `sportscanner/crawlers/parsers/better/`.

## API shape

Base: `https://better-admin.org.uk/api/activities/venue/{venue_slug}/activity/{activity_slug}/times?date=YYYY-MM-DD`

Every request goes through `activity_slug_pairs(sport, venue_slug)` in
`better/core/activities.py`, which returns a list of `(primary, fallback)` slug
pairs. One HTTP request is generated per pair; the fallback is only tried if the
primary comes back as an HTTP error (see `docs/crawlers.md` "Retries" section for
the general fallback mechanism). Adding a venue quirk is a one-line entry in
`_VENUE_OVERRIDES`, not an `if` branch in the request builder.

Headers: `origin: https://bookings.better.org.uk`, a matching `referer`, and a
desktop Chrome `user-agent`. No auth token needed — this is a public API.

## The v1 → v2 migration

Better is mid-rollout of a `/v2` times endpoint, done **per venue and per
activity**, not globally. A venue can be on v2 for badminton and still on v1 for
squash. This is why every sport's default is a `(primary, fallback)` pair rather
than a single slug — whichever version the venue hasn't migrated to yet answers
with an HTTP error (422 or 404), and the loop falls back to the other.

**Badminton and squash**: only the version suffix changes, the slug name stays
fixed (`badminton-40min` → `badminton-40min/v2`; squash's name also changes,
`squash-court-40min` (v1) → `squash-40min` (v2)).

**Pickleball is the one where the slug spelling itself changes between versions**,
not just the suffix:

- v1 (legacy): plural, no version suffix — `pickleball-40mins`, `pickleball-60mins`
- v2 (migrated): singular, with suffix — `pickleball-40min/v2`, `pickleball-60min/v2`

Confirmed v1-only (legacy) venues, as of July 2026: `score-leisure-centre`,
`barking-sporthouse-and-gym`, `waltham-forest-feel-good-centre`,
`walthamstow-leisure-centre`, `leytonstone-leisure-centre`. v2 answers these with a
404/500.

The rest of the pickleball roster (confirmed 17 of 22 configured venues,
including `lee-valley-velopark`, `woolwich-waves-leisure-centre`,
`the-plumstead-centre`) have already migrated and are v2-only. v1 does **not**
404 cleanly for them — it answers with Better's generic
`"The date should be within the valid days you are able to view."` 422, which
reads exactly like "this venue doesn't offer this activity" rather than "wrong
slug". That ambiguity is what let this sit broken for a while: the fallback
existed, but its slug was still plural (`pickleball-40mins/v2`), which doesn't
exist either way and 500s. Fixed by making the fallback singular
(`pickleball-40min/v2`) — see `_DEFAULTS["pickleball"]` in `activities.py`.

**Lesson**: a 4xx from this API is not reliable evidence that an activity/duration
genuinely isn't offered. Check the venue's actual category listing (below) before
concluding that.

## Discovering a venue's real activity slugs

`GET /api/activities/venue/{slug}/categories/{sport}` lists what a venue actually
has under that sport category, including children that don't follow the standard
duration-based naming:

```
curl 'https://better-admin.org.uk/api/activities/venue/shene-sports-and-fitness-centre/categories/pickleball'
```

returns a tree with `slug`, `v2_slug`, `v1_slug` (null if the activity is v2-only),
and `v2_type` (`"resources"` for normal court-booking activities, `"ticketed"` for
fixed-session/drop-in activities — these two types likely have different response
shapes; see the Britannia/Shene section below). Use this before guessing
40min/60min variants by hand — it's how the two venue overrides below were found.

## Venue overrides (`_VENUE_OVERRIDES`)

- **`shene-sports-and-fitness-centre` / badminton**: doesn't split into 40/60min —
  exposes a single `badminton-court` activity (v2 only, v1 404s) of mixed
  durations.
- **`shene-sports-and-fitness-centre` / pickleball**: exposes `pickleball-court`
  (a normal `"resources"`-type court-booking activity) *and* `pickleball-drop-in`
  (a `"ticketed"` activity — a different session type). Configured to use
  `pickleball-court/v2` as primary.
- **`britannia-leisure-centre` / pickleball**: has *only* `pickleball-drop-in`, no
  separate court-booking activity at all.

The `pickleball-drop-in` (`"ticketed"`) response shape hasn't actually been
validated against real data — both venues had zero scheduled sessions in the
window checked (July 2026), so the endpoint returns `{"data": []}` either way. If
`pickleball-drop-in` ever comes back non-empty and parses wrong (or throws), start
here: `BetterApiResponseSchema` in `better/core/schema.py` was written against the
`"resources"` shape, and a ticketed session may not look the same.

## Known venue-level gaps (not crawler bugs)

- **Finsbury Leisure Centre**: was configured for pickleball in `venues.json` but
  Better's own category listing for it (`/categories`) doesn't include pickleball
  at all — the venue genuinely doesn't offer it. Removed from `venues.json` and
  patched directly in prod `sportsvenue.sports` (July 2026). If it starts
  appearing in Better's category list later, re-add it.
- **Kings Hall Leisure Centre** (badminton): `GET /categories` for this venue
  returns `{"data": []}` — Better isn't exposing *any* bookable category for it
  right now, badminton or otherwise. Likely closed/suspended on Better's side,
  not something fixable in our config. Re-check periodically; if it comes back
  it'll need no code change, since the standard badminton slug pair already
  covers it.

## Design decisions worth preserving

- The `(sport, venue_slug) -> overrides` dict structure in `activities.py` exists
  specifically so a venue quirk is a one-line data entry, not a branch in the
  request builder. Keep new quirks there.
- Don't trust a 4xx from this API as "activity not offered" without checking
  `/categories` first — Better's error message is identical whether the slug is
  wrong or the activity genuinely isn't offered.
