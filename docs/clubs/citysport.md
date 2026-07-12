# CitySport (City St George's, University of London)

1 venue, `https://citysport.org.uk`. Badminton.
Code: `sportscanner/crawlers/parsers/citysports/`.

## Status: broken — TLS-level connection reset, not an application bug

`badminton` table has **zero rows ever** for this venue (`composite_key`
`99434b56`). Confirmed live (July 2026): the request fails before any HTTP
response — `httpx`/`httpcore` raises a bare `ConnectError` during the TLS
handshake against `bookings.citysport.org.uk`.

This is not a DNS, certificate, or firewall issue:

- DNS resolves fine (`138.40.77.42`).
- The certificate is valid and includes `bookings.citysport.org.uk` in its SAN list.
- `curl` (any User-Agent, including a plain default one) completes the TLS
  handshake and gets a normal response every time.
- Python's `ssl` module (both raw `ssl.wrap_socket` and via `httpx`) gets
  `ConnectionResetError: [Errno 54] Connection reset by peer` during the same
  handshake, consistently, regardless of the `User-Agent` header sent — the
  reset happens at the TLS layer, before any HTTP headers are even transmitted.

This is almost certainly **TLS fingerprinting** (JA3 or equivalent): a WAF/CDN in
front of `bookings.citysport.org.uk` distinguishing Python's OpenSSL `ClientHello`
signature from curl's/a real browser's and resetting the connection for the
former. Headers can't fix this — the block happens before any header is sent.

## What would actually fix it

A TLS-impersonating HTTP client (e.g. `curl_cffi`, which mimics a real browser's
JA3 fingerprint) in place of `httpx` for this one provider. This is a new
dependency and a different request path from every other provider (all of which
use the shared `httpxAsyncClient()` in `crawlers/anonymize/proxies.py`), so it's a
deliberate, scoped decision, not a quick patch — flagged for a follow-up rather
than done here.

## Status (July 2026)

Confirmed broken by the mechanism above, not fixed. 1 venue affected (this is the
provider's entire roster).
