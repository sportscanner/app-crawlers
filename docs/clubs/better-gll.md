# Better / GLL (Greenwich Leisure Limited)

52 London venues, `https://www.better.org.uk`. Badminton (43 venues), squash (14 venues), pickleball (40 venues), tennis (15 venues).
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
desktop Chrome `user-agent`. No auth token needed: this is a public API.

## The v1 to v2 migration

Better is mid-rollout of a `/v2` times endpoint, done per venue and per
activity, not globally. A venue can be on v2 for badminton and still on v1 for
squash. This is why every sport default is a `(primary, fallback)` pair rather
than a single slug: whichever version the venue has not migrated to yet answers
with an HTTP error (422 or 404), and the loop falls back to the other.

**Badminton and squash**: only the version suffix changes, the slug name stays
fixed (`badminton-40min` to `badminton-40min/v2`; squash name also changes,
`squash-court-40min` (v1) to `squash-40min` (v2)).

**Pickleball is the one where the slug spelling itself changes between versions**,
not just the suffix:

- v1 (legacy): plural, no version suffix: `pickleball-40mins`, `pickleball-60mins`
- v2 (migrated): singular, with suffix: `pickleball-40min/v2`, `pickleball-60min/v2`

As of August 2026 the v1 to v2 pickleball migration is complete across all
tracked London venues: every venue that was previously listed as "v1-only"
(`score-leisure-centre`, `barking-sporthouse-and-gym`,
`waltham-forest-feel-good-centre`, `walthamstow-leisure-centre`,
`leytonstone-leisure-centre`) now 422s on the plural v1 slug and answers the
singular v2 slug with live data. `_DEFAULTS["pickleball"]` therefore uses
singular/v2 as primary and keeps plural/v1 only as a fallback for any straggler
venue. (Earlier, when roughly half the roster was still on v1, the order was
reversed; the pair mechanism exists precisely so flipping the order is a
config change, not code.)

The migration history also produced this project's clearest lesson about
error semantics on this API: a 4xx from it is not reliable evidence that an
activity/duration genuinely is not offered. During the rollout, v1 answered
with the generic `"The date should be within the valid days you are able to
view."` 422 for migrated venues, which reads like "this venue does not offer
this activity" rather than "wrong slug". Check the venue actual category
listing (below) before concluding anything from a 4xx alone.

## Customer-facing booking URLs

`bookings.better.org.uk` links are built from activity slugs, and two things
about those links differ from the API request slugs:

1. **No `/v2` segment, ever.** The public booking site's URL scheme never
   includes the version suffix. The canonical public spelling is whatever the
   categories endpoint reports as `slug` (e.g. `pickleball-60min`), even for
   venues whose data resolves through v2 internally.
   `public_activity_slug()` in `better/core/activities.py` strips the suffix;
   embedding a raw `/v2` slug produces a dead link with a spurious extra path
   segment.

2. **Primary and fallback spellings can differ.** A venue whose primary
   variant 422s gets its data from the fallback variant, whose public slug may
   be spelled differently (the pickleball plural/singular split being the
   example). Each Better scraper therefore also sets `fallback_booking_urls`
   on its requests, and `BaseCrawler._fetch_and_transform` swaps the stamped
   `booking_url` for the matching entry whenever a fallback variant is the one
   that actually returned the data. Without this, a v2-only venue would emit
   rows linking to the dead plural spelling, which is exactly what users saw
   before the August 2026 fix (e.g.
   `.../lee-valley-velopark/pickleball-60mins/...` instead of
   `.../lee-valley-velopark/pickleball-60min/...`).

## Discovering a venue real activity slugs

`GET /api/activities/venue/{slug}/categories/{sport}` lists what a venue actually
has under that sport category, including children that do not follow the standard
duration-based naming:

```
curl 'https://better-admin.org.uk/api/activities/venue/shene-sports-and-fitness-centre/categories/pickleball'
```

returns a tree with `slug`, `v2_slug`, `v1_slug` (null if the activity is v2-only),
and `v2_type` (`"resources"` for normal court-booking activities, `"ticketed"` for
fixed-session/drop-in activities). Use this before guessing 40min/60min variants by hand.

`GET /api/activities/venues` returns all UK venues managed by Better with official slugs,
postcodes, coordinates, and metadata.

## Venue overrides (`_VENUE_OVERRIDES`)

- **Richmond upon Thames venues** (`shene-sports-and-fitness-centre`, `hampton-sports-and-fitness-centre`,
  `teddington-sports-centre`, `whitton-sports-and-fitness-centre`):
  - Badminton: do not split into 40/60min, expose a single `badminton-court/v2` activity.
  - Pickleball: expose `pickleball-court/v2` (a normal court-booking activity) alongside drop-in sessions.
  - Squash (`teddington-sports-centre`): runs 45-minute squash sessions (`squash-45min/v2`).
- **`britannia-leisure-centre` / pickleball**: exposes `pickleball-60min/v2` court booking
  as well as `pickleball-drop-in/v2`.
- **Tennis multi-court venues**:
  - `islington-tennis-centre`: indoor and outdoor courts (`tennis-court-outdoor/v2`, `tennis-court-indoor/v2`).
  - `lee-valley-hockey-and-tennis-centre`: indoor and outdoor courts (`tennis-court-outdoor/v2`, `tennis-court-indoor/v2`).
  - `sutton-sports-village`: clay, dome, and outdoor courts (`tennis-court-clay/v2`, `tennis-court-dome/v2`, `tennis-court-outdoor/v2`).

## Squash coverage (14 London venues)

Squash availability verified live across London Better centres:
- Britannia Leisure Centre
- Canons Leisure Centre
- Clissold Leisure Centre
- Crystal Palace National Sports Centre
- Finsbury Leisure Centre
- Hammersmith Fitness and Squash Centre
- Ironmonger Row Baths
- Kensington Leisure Centre
- Oasis Sports Centre
- Sobell Leisure Centre
- Swiss Cottage Leisure Centre
- Teddington Sports Centre (45-minute court bookings)
- Walthamstow Leisure Centre
- Woolwich Waves (formerly Waterfront Leisure Centre)

## Tennis coverage (15 London venues)

Discovered via `GET /api/activities/venue/{slug}/categories/tennis` (requires `origin`/`referer` headers):
- `barnet-burnt-oak-leisure-centre` (outdoor)
- `britannia-leisure-centre` (outdoor)
- `charlton-lido` (outdoor)
- `crystal-palace-leisure-centre` (outdoor)
- `gunnersbury-park-sports-hub` (outdoor)
- `hackney-parks` (outdoor courts across Hackney parks)
- `hampton-sports-and-fitness-centre` (outdoor)
- `islington-tennis-centre` (indoor + outdoor)
- `lee-valley-hockey-and-tennis-centre` (indoor + outdoor)
- `new-barnet-leisure-centre` (outdoor)
- `queensmead-sports-centre` (outdoor)
- `sutton-sports-village` (clay, dome, outdoor)
- `teddington-sports-centre` (outdoor)
- `waltham-forest-feel-good-centre` (outdoor)
- `whitton-sports-and-fitness-centre` (outdoor)

Note: Swiss Cottage, Kensington, and Clissold leisure centres carry generic marketing copy
for tennis lessons on their public web pages, but none has a bookable tennis category via the API.

## London venue expansion (August 2026)

Full sweep across all 256 Better/GLL UK venues filtered to Greater London boroughs:
- 52 total London Better venues tracked (36 existing in `venues.json` updated with expanded sports, 16 net-new London venues added).
- Sports breakdown: 43 badminton venues, 14 squash venues, 40 pickleball venues, 15 tennis venues.
- 16 net-new London venues:
  - `botwell-green-leisure-centre` (Hillingdon): badminton, pickleball
  - `charlton-lido` (Greenwich): tennis
  - `edmonton-leisure-centre` (Enfield): badminton, pickleball
  - `hackney-parks` (Hackney): tennis
  - `hampton-sports-and-fitness-centre` (Richmond): badminton, pickleball, tennis
  - `hillingdon-sports-leisure-centre` (Hillingdon): badminton, pickleball
  - `lee-valley-hockey-and-tennis-centre` (Waltham Forest / Newham): tennis
  - `monks-hill-sports-centre` (Croydon): badminton, pickleball
  - `new-barnet-leisure-centre` (Barnet): tennis
  - `peter-may-sports-centre` (Waltham Forest): badminton, pickleball
  - `platinum-jubilee-leisure-centre` (Hillingdon): badminton, pickleball
  - `southbury-leisure-centre` (Enfield): badminton, pickleball
  - `sutton-sports-village` (Sutton): badminton, pickleball, tennis
  - `teddington-sports-centre` (Richmond): badminton, squash, pickleball, tennis
  - `waddon-leisure-centre` (Croydon): badminton, pickleball
  - `whitton-sports-and-fitness-centre` (Richmond): badminton, pickleball, tennis

All venue additions and updates are output in `reports/venue-fragments/better.json`.

## Design decisions worth preserving

- The `(sport, venue_slug) -> overrides` dict structure in `activities.py` exists
  specifically so a venue quirk is a one-line data entry, not a branch in the
  request builder. Keep new quirks there.
- Do not trust a 4xx from this API as "activity not offered" without checking
  `/categories` first: Better error message is identical whether the slug is
  wrong or the activity genuinely is not offered.
