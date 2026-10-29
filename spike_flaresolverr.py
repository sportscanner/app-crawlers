"""Spike: verify ClubSpark access from a GitHub-hosted runner."""
import json
import os
import re
import time

import httpx

FS = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")
BASE = "https://clubspark.lta.org.uk"
GREEN, RED = "\033[32m", "\033[0m"


def ok(label, passed, detail=""):
    print(f"{GREEN if passed else RED}{'PASS' if passed else 'FAIL'}{GREEN if passed else RED} {label} {detail}{GREEN}")


def clubspark_url(slug):
    return (
        f"{BASE}/v0/VenueBooking/{slug}/GetVenueSessions"
        f"?resourceID=&startDate=2026-10-30&endDate=2026-11-05&roleId="
    )


def parse(body):
    m = re.search(r"<pre[^>]*>(.*)</pre>", body, re.S)
    text = m.group(1) if m else body
    data = json.loads(text)
    return sum(
        1
        for res in data.get("Resources", [])
        for day in res.get("Days", [])
        for s in day.get("Sessions", [])
        if s.get("Category") == 1000
    )


def main():
    with httpx.Client(timeout=30) as c:
        ip = c.get("https://api.ipify.org?format=json").json()["ip"]
    print(f"runner egress ip: {ip}")

    slugs = ["FinsburyPark", "kenningtonpark", "claphamcommon", "BurgessParkSouthwark", "HackneyDowns"]

    # 1. direct
    t = time.time()
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        r = c.get(clubspark_url(slugs[0]), headers={"referer": f"{BASE}/{slugs[0]}/Booking/BookByDate"})
    print(f"direct ClubSpark: HTTP {r.status_code} in {time.time()-t:.1f}s body={r.text[:60]!r}")
    ok("direct ClubSpark", r.status_code == 200)

    # 2. solver session
    session = httpx.post(FS, json={"cmd": "sessions.create"}, timeout=60).json()["session"]
    good = 0
    total = 0
    started = time.time()
    try:
        for slug in slugs:
            t = time.time()
            payload = httpx.post(
                FS,
                json={"cmd": "request.get", "url": clubspark_url(slug), "session": session, "maxTimeout": 90000},
                timeout=120,
            ).json()
            sol = payload.get("solution") or {}
            status = sol.get("status", 0)
            try:
                bookable = parse(sol.get("response", "")) if status == 200 else 0
            except Exception:
                bookable = -1
            total += max(bookable, 0)
            good += 1 if status == 200 and bookable > 0 else 0
            print(f"  solver {slug:24} status={status} bookable={bookable:4} {time.time()-t:5.2f}s")
    finally:
        httpx.post(FS, json={"cmd": "sessions.destroy", "session": session}, timeout=30)
    print(f"solver total: {good}/{len(slugs)} live, {total} bookable in {time.time()-started:.1f}s")
    ok("ClubSpark via solver", good >= 4)


    # 4. Playtomic direct
    t = time.time()
    r = httpx.get(
        "https://playtomic.com/api/clubs/availability",
        params={"tenant_id": "113065cd-202c-46e7-9ef4-a2af650983cf", "date": "2026-11-01", "sport_id": "PADEL"},
        headers={"user-agent": "Mozilla/5.0", "referer": "https://playtomic.com/"},
        timeout=30,
    )
    print(f"Playtomic direct: HTTP {r.status_code} in {time.time()-t:.1f}s")
    ok("Playtomic direct", r.status_code == 200)


if __name__ == "__main__":
    main()
