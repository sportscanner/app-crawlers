# Club-specific crawler documentation

One file per booking provider ("club" in the loose sense — some are single venues,
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
| Better / GLL | [better-gll.md](better-gll.md) | badminton, squash, pickleball | 35 | healthy (3 known venue-level gaps) |
| Active Lambeth | [active-lambeth.md](active-lambeth.md) | badminton, squash | 4 | healthy |
| Haringey Council | [haringey.md](haringey.md) | badminton | 2 | healthy |
| Everyone Active | [everyone-active.md](everyone-active.md) | badminton | 12 | healthy (fixed — proxy with retry-on-403, free-tier pool is partly blocklisted) |
| Tower Hamlets (Be Well) | [tower-hamlets.md](tower-hamlets.md) | badminton | 4 | healthy (fragile auth pattern) |
| CitySport (City St George's, University of London) | [citysport.md](citysport.md) | badminton | 1 | healthy (fixed via `curl_cffi` TLS impersonation) |
| Southwark Leisure | [southwark-leisure.md](southwark-leisure.md) | badminton, pickleball | 2 | healthy |
| Decathlon | [decathlon.md](decathlon.md) | pickleball | 1 | healthy |
| Matchi | [matchi.md](matchi.md) | padel | 10 | healthy (2 venues genuinely unbookable) |
| Playtomic | [playtomic.md](playtomic.md) | padel | 33 | healthy |
| South Croydon Sports Club | [south-croydon-sports-club.md](south-croydon-sports-club.md) | (none implemented) | 1 | **not implemented** |

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
