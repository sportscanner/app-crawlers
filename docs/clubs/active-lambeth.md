# Active Lambeth

4 venues, `https://active.lambeth.gov.uk/`. Badminton, squash.
Code: `sportscanner/crawlers/parsers/activelambeth/`.

## API shape

Base: `https://flow.onl/api/activities/venue/{venue_slug}/activity/{activity_slug}/times?date=YYYY-MM-DD`

`flow.onl` is a white-labelled instance of the same Gladstone booking engine that
powers Better/GLL (`better-admin.org.uk`) and Haringey's booking site — same URL
shape, same response schema (`BetterLeisureResponseParserStrategy` is reused
as-is, no separate parser exists for this provider). See
[better-gll.md](better-gll.md) for the general v1/v2 background.

Headers: `origin: https://lambethcouncil.bookings.flow.onl`, matching `referer`,
desktop Chrome `user-agent`. No auth.

## Activity slugs

Badminton uses `badminton-40min` / `badminton-60min` with **no version suffix at
all** — this deployment hasn't needed the `/v2` split that Better and Haringey
have. Squash follows the same no-suffix pattern. Don't assume Better's v1/v2
quirks apply here; this is a separate Gladstone deployment and has its own
migration timeline (verify against this venue directly, don't copy Better's
config).

## Status (July 2026)

Confirmed live: all 4 badminton venues and both squash venues return data. No
known issues.
