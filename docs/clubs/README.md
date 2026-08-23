# Club-specific crawler documentation

One file per booking provider ("club" in the loose sense, some are single venues,
some are councils running dozens). Each file covers what `docs/crawlers.md` doesn't:
the provider's actual API shape, its slug/ID quirks, which venues are known-broken
and why, and design decisions specific to that provider that aren't obvious from
the code alone.

Read `docs/crawlers.md` first for the shared architecture (BaseCrawler, the
semaphore, the circuit breaker, fallback URLs). This folder is the per-provider
detail that sits underneath it.

## Index

| Provider | File | Sports | Venues | Status |
|---|---|---|---|---|
| Better / GLL | [better-gll.md](better-gll.md) | badminton, squash, pickleball, tennis | 35 | healthy (3 known venue-level gaps); tennis added Aug 2026, 5 of 35 venues confirmed so far, verified end-to-end (343 real slots landed in `tennis` table on first full pipeline run) |
| Active Lambeth | [active-lambeth.md](active-lambeth.md) | badminton, squash | 4 | healthy |
| Haringey Council | [haringey.md](haringey.md) | badminton | 2 | healthy |
| Everyone Active | [everyone-active.md](everyone-active.md) | badminton, squash | 15 (12 badminton, 6 squash) | healthy (proxy with retry-on-403) |
| Tower Hamlets (Be Well) | [tower-hamlets.md](tower-hamlets.md) | badminton | 4 | healthy (fragile auth pattern) |
| CitySport (City St George's, University of London) | [citysport.md](citysport.md) | badminton | 1 | healthy (fixed via `curl_cffi` TLS impersonation) |
| Southwark Leisure | [southwark-leisure.md](southwark-leisure.md) | badminton, pickleball | 2 | healthy |
| Decathlon | [decathlon.md](decathlon.md) | pickleball | 1 | healthy |
| Matchi | [matchi.md](matchi.md) | padel, tennis | 22 padel + 3 tennis | healthy (2 padel venues genuinely unbookable): 12 new London/commuter padel venues added Aug 2026, tennis confirmed live with populated slots at Down Hall Hotel |
| Playtomic | [playtomic.md](playtomic.md) | padel, tennis | 33 padel + 1 tennis | healthy; tennis added Aug 2026, verified end-to-end (318 real slots landed in `tennis` table on first full pipeline run), only 1 venue so far |
| South Croydon Sports Club | [south-croydon-sports-club.md](south-croydon-sports-club.md) | (none implemented) | 1 | **not implemented** |
| UEL SportsDock | [uel-sportsdock.md](uel-sportsdock.md) | badminton | 1 | healthy (added July 2026) |
| Places Leisure | [places-leisure.md](places-leisure.md) | badminton, pickleball | 8 | healthy (added July 2026) |
| Vision RCL (Redbridge) | [vision-rcl.md](vision-rcl.md) | badminton, squash | 3 | healthy (added Aug 2026, flow.onl v2 Gladstone tenant) |
| CourtReserve (Lemon Pickleball) | [courtreserve.md](courtreserve.md) | pickleball | 19 | healthy (added Aug 2026, 19 London venues on orgId 13469) |
| Stratford Padel Club | [stratford-padel.md](stratford-padel.md) | padel | 1 | healthy (added Aug 2026, TPC-MatchPoint ASP.NET grid) |
| Padel Mates | [padel-mates.md](padel-mates.md) | padel | 15 | healthy (added Aug 2026, 15 London/commuter venues verified) |
| Mytime Active (Bromley) | [mytime-active.md](mytime-active.md) | badminton, squash | 2 | healthy (added Aug 2026, Gladstone Go tenant) |
| LTA ClubSpark | [clubspark.md](clubspark.md) | tennis | 6 (starting seed) | new (added Aug 2026); API confirmed live in research, but got Cloudflare 403 on re-verification from a different IP: needs a real scheduled run checked before calling this healthy |

Better / GLL, Active Lambeth, and Haringey all run on the same underlying
Gladstone booking engine (Better's is at `better-admin.org.uk`; the other two are
white-labelled instances of the same platform at `flow.onl`). They share the same
`/api/activities/venue/{slug}/activity/{activity}/times` URL shape and the same
v1/v2 migration quirk, which is why `BetterLeisureResponseParserStrategy` and
`BetterStyleCrawler` are reused across all three rather than each having its own
parser. See [better-gll.md](better-gll.md) for the shared mechanics; the other two
files only cover what's different for that specific deployment.

## How this was compiled

Everything in these files was checked live against the provider's real API in
July 2026 (not inferred from old comments or assumptions) by running each
provider's actual `coroutines()` entry point against production venue data, then
following up any zero-data venue with direct API calls to determine which of:
wrong slug, venue-level outage, or genuine no-availability, actually explains it.
The one broadly reusable technique that came out of this: Better/GLL exposes
`GET /api/activities/venue/{slug}/categories/{sport}`, which lists a venue's
*actual* bookable activity slugs (including ones that don't follow the usual
40min/60min naming). Hit that before guessing slug variants by hand.
