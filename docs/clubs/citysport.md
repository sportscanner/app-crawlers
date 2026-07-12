# CitySport (City St George's, University of London)

1 venue, `https://citysport.org.uk`. Badminton.
Code: `sportscanner/crawlers/parsers/citysports/`.

## The problem: TLS-level connection reset, not an application bug

`badminton` table had **zero rows ever** for this venue (`composite_key`
`99434b56`) before this was fixed. The request failed before any HTTP
response — `httpx`/`httpcore` raised a bare `ConnectError` during the TLS
handshake against `bookings.citysport.org.uk`.

This was not a DNS, certificate, or firewall issue:

- DNS resolves fine (`138.40.77.42`).
- The certificate is valid and includes `bookings.citysport.org.uk` in its SAN list.
- `curl` (any User-Agent, including a plain default one) completes the TLS
  handshake and gets a normal response every time.
- Python's `ssl` module (both raw `ssl.wrap_socket` and via `httpx`) got
  `ConnectionResetError: [Errno 54] Connection reset by peer` during the same
  handshake, consistently, regardless of the `User-Agent` header sent — the
  reset happened at the TLS layer, before any HTTP headers were even
  transmitted.

This is **TLS fingerprinting** (JA3 or equivalent): a WAF/CDN in front of
`bookings.citysport.org.uk` distinguishing Python's OpenSSL `ClientHello`
signature from curl's/a real browser's and resetting the connection for the
former. Headers can't fix this — the block happens before any header is sent.

## The fix: `curl_cffi` instead of `httpx`, for this provider only

`CitySportsCrawler` now bypasses `BaseCrawler`'s shared `_send_concurrent_requests`
fetch loop (which is hardwired to `httpx`) and overrides `ScraperCoroutines`
directly — same pattern Matchi and Playtomic already use, for their own,
different reasons (their APIs return all venues per date rather than one venue
per URL). CitySport's `_fetch_venue_date` uses `curl_cffi.requests.AsyncSession`
with `impersonate="chrome124"`, which mimics a real Chrome TLS fingerprint and
gets a clean `200` every time.

Why bypass `BaseCrawler` rather than make the shared fetch loop
transport-agnostic: `_fetch_and_transform` in `core/interfaces.py` specifically
catches `httpx.HTTPStatusError` to distinguish "venue doesn't offer this
activity" (4xx, expected) from "provider is down" (5xx/connection error, counts
against the circuit breaker) — see that file's docstring. `curl_cffi` raises its
own `curl_cffi.requests.exceptions.HTTPError`, not `httpx.HTTPStatusError`, so a
generic swap would silently misclassify every CitySport 4xx as an infra failure.
Making the shared loop transport-agnostic is possible but touches behaviour every
other provider depends on for very little gain when only one provider needs it —
scoping the change to CitySport's own override keeps the blast radius at zero for
the other 10 providers. `_fetch_venue_date` reimplements the same 4xx/5xx
distinction locally (see the `CurlHTTPError` vs generic `Exception` branches),
just without a shared circuit breaker (not worth building for a single-venue
provider — if that changes, revisit).

Still reuses `CitySportsBadmintonRequestStrategy.generate_request_details()` (URL
+ headers) and `CitySportsResponseParserStrategy.parse()` (response → slots)
unchanged — only the actual network call changed.

New dependency: `curl_cffi` (in `requirements.txt`). Ships its own bundled
libcurl-impersonate binary in the wheel; no extra system packages needed beyond
what the Dockerfile (Debian slim) already has.

## Status (July 2026)

Fixed and confirmed live through the real `coroutines()` entry point (22 real
slots returned for the venue, including available ones). If CitySport starts
failing again, check whether Chrome's TLS fingerprint has changed enough that
`impersonate="chrome124"` needs bumping to a newer Chrome version string before
assuming anything else is wrong.
