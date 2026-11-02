"""Remove legacy Playtomic venue duplicates and fix stale slugs in production.

Nine Playtomic venues were stored twice: once under the API tenant_uid
(trailing dashes, triple dashes, or an "@" in the slug) and once under the
public playtomic.com slug. Both rows map to the same Playtomic tenant, so the
crawler fetched the same availability twice and the search API rendered two
cards for one physical venue, often with different "last updated" times.

Three further rows were seeded from a national list under synthetic slugs that
do not resolve on playtomic.com, so they could never be crawled. This script
renames them to their confirmed public slugs and computes the new composite
key. `venues.json` and `SLUG_TO_TENANT_ID` already contain the corrected
entries.

The canonical row is kept. The legacy row is kept but its `sports` array is
emptied so it drops out of `get_venues_by_sport_offering()` and the search
radius queries, and its slot rows are deleted. Keeping the `sportsvenue` row
preserves its `composite_key` for anyone who favourited the old listing; the
venue detail page still resolves, but it no longer appears as a separate
search result.

Run a dry run first:

    ENV=prod python scripts/dedupe_playtomic_venues.py

Then apply:

    ENV=prod python scripts/dedupe_playtomic_venues.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text

from sportscanner.storage.postgres.database import engine
from sportscanner.storage.postgres.utils import generate_composite_key

# legacy slug -> canonical slug
LEGACY_TO_CANONICAL: Dict[str, str] = {
    "battersea-park-millennium-arena-": "battersea-park-millennium-arena",
    "padel-waltham-abbey": "padel-district-waltham-abbey",
    "padel-people---wimbledon": "padel-people-wimbledon",
    "padel-social-club---earls-court": "padel-social-club-earls-court",
    "padel-social-club---the-o2": "padel-social-club-the-o2",
    "powerleague-mill-hill-": "powerleague-mill-hill",
    "powerleague-shoreditch-": "powerleague-shoreditch",
    "rocks-lane-@-dyrham-park-country-club": "rocks-lane-dyrham-park-country-club",
    "tour-padel---avery-hill-campus-": "tour-padel-avery-hill-campus",
}

# DB slug -> (public playtomic.com slug, tenant_id). These three rows were
# seeded from a national list under synthetic slugs that do not resolve on
# playtomic.com, so they could never be crawled. The public pages and tenant
# ids were confirmed live in November 2026.
SLUG_RENAMES: Dict[str, Tuple[str, str]] = {
    "s3-padel-finchley-road": (
        "s3-finchley-rd",
        "113065cd-202c-46e7-9ef4-a2af650983cf",
    ),
    "padelhub-kt19-epsom": (
        "the-padel-hub-kt19-epsom",
        "04dd6b80-e488-4af3-b740-78704af847ef",
    ),
    "essendon-padel-club": (
        "essendon-country-club-uk",
        "88f92dcc-342f-4852-b1b6-19b2276c3e0a",
    ),
}

SLOT_TABLES = ("badminton", "squash", "pickleball", "padel", "tennis")


def _venue(conn, slug: str) -> Tuple[str, Iterable[str]] | None:
    row = conn.execute(
        text("""
            select composite_key, sports
            from sportsvenue
            where organisation_website = 'https://playtomic.com'
              and slug = :slug
            """),
        {"slug": slug},
    ).first()
    if row is None:
        return None
    return row.composite_key, list(row.sports or [])


def _slot_counts(conn, composite_key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for table in SLOT_TABLES:
        counts[table] = conn.execute(
            text(f"select count(*) from {table} where composite_key = :key"),
            {"key": composite_key},
        ).scalar_one()
    counts["slot_history"] = conn.execute(
        text("select count(*) from slot_history where composite_key = :key"),
        {"key": composite_key},
    ).scalar_one()
    return counts


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the legacy slot rows and empty the legacy sports array",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    with engine.begin() as conn:
        for legacy_slug, canonical_slug in LEGACY_TO_CANONICAL.items():
            legacy = _venue(conn, legacy_slug)
            canonical = _venue(conn, canonical_slug)
            if legacy is None:
                print(f"skip {legacy_slug}: no sportsvenue row")
                continue
            if canonical is None:
                print(f"skip {legacy_slug}: canonical {canonical_slug} is missing")
                continue

            legacy_key, legacy_sports = legacy
            canonical_key, canonical_sports = canonical
            merged_sports = sorted(set(canonical_sports) | set(legacy_sports))
            counts = _slot_counts(conn, legacy_key)

            print(
                f"{legacy_slug} ({legacy_key}) -> {canonical_slug} "
                f"({canonical_key}): sports={merged_sports} slots={counts}"
            )

            if not args.apply:
                continue

            conn.execute(
                text(
                    "update sportsvenue set sports = :sports "
                    "where composite_key = :key"
                ),
                {"sports": merged_sports, "key": canonical_key},
            )
            # Emptying the array removes the legacy row from sport-scoped
            # venue queries without deleting the composite_key a favourite
            # might still reference.
            conn.execute(
                text(
                    "update sportsvenue set sports = '{}' " "where composite_key = :key"
                ),
                {"key": legacy_key},
            )
            for table in SLOT_TABLES:
                conn.execute(
                    text(f"delete from {table} where composite_key = :key"),
                    {"key": legacy_key},
                )
            conn.execute(
                text("delete from slot_history where composite_key = :key"),
                {"key": legacy_key},
            )

        for old_slug, (new_slug, tenant_id) in SLUG_RENAMES.items():
            row = _venue(conn, old_slug)
            if row is None:
                print(f"skip rename {old_slug}: no sportsvenue row")
                continue
            old_key, sports = row
            new_key = generate_composite_key(["https://playtomic.com", new_slug])
            conflict = conn.execute(
                text("""
                    select composite_key from sportsvenue
                    where organisation_website = 'https://playtomic.com'
                      and (slug = :new_slug or composite_key = :new_key)
                    """),
                {"new_slug": new_slug, "new_key": new_key},
            ).first()
            if conflict is not None:
                print(
                    f"skip rename {old_slug}: {new_slug} already exists "
                    f"({conflict.composite_key})"
                )
                continue

            counts = _slot_counts(conn, old_key)
            print(
                f"rename {old_slug} ({old_key}) -> {new_slug} ({new_key}), "
                f"tenant_id={tenant_id}, sports={sports}, slots={counts}"
            )
            if not args.apply:
                continue

            for table in SLOT_TABLES:
                conn.execute(
                    text(
                        f"update {table} set composite_key = :new_key "
                        "where composite_key = :old_key"
                    ),
                    {"new_key": new_key, "old_key": old_key},
                )
            conn.execute(
                text(
                    "update slot_history set composite_key = :new_key "
                    "where composite_key = :old_key"
                ),
                {"new_key": new_key, "old_key": old_key},
            )
            conn.execute(
                text(
                    "update sportsvenue set slug = :new_slug, "
                    "composite_key = :new_key where composite_key = :old_key"
                ),
                {"new_slug": new_slug, "new_key": new_key, "old_key": old_key},
            )

    print("done (dry run)" if not args.apply else "done (applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
