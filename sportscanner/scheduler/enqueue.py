"""Scheduler enqueue entry point.

    python -m sportscanner.scheduler.enqueue --provider playtomic --dry-run

Reads the existing venue registry, computes the due (provider, venue, sport,
date) pairs from the freshness tiers, and upserts them into `crawl_job`.
Idempotent and independent of how long any crawl takes.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import Engine

from sportscanner.logger import logging
from sportscanner.scheduler.providers import PROVIDERS
from sportscanner.scheduler.queue import (
    enqueue_jobs,
    enqueue_lock,
    load_last_success,
    load_venues,
    plan_jobs,
)
from sportscanner.scheduler.tiers import DEFAULT_HORIZON_DAYS, horizon_dates
from sportscanner.storage.postgres.database import engine as default_engine


def _csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def run_enqueue(
    engine: Engine,
    *,
    providers: Optional[Sequence[str]] = None,
    sports: Optional[Sequence[str]] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    provider_keys = list(providers) if providers else sorted(PROVIDERS)
    unknown = sorted(set(provider_keys) - set(PROVIDERS))
    if unknown:
        raise SystemExit(
            f"Unknown provider(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(PROVIDERS))}"
        )

    dates = horizon_dates(now.date(), horizon_days)
    sport_filter = set(sports) if sports else None

    with enqueue_lock(engine) as acquired:
        if not acquired:
            logging.warning(
                "Another scheduler is already enqueuing; skipping this tick"
            )
            return 0

        total = 0
        for provider in provider_keys:
            venues = load_venues(engine, provider)
            if not venues:
                logging.debug(f"No venues registered for provider {provider}")
                continue
            last_success = load_last_success(engine, provider, dates[0], dates[-1])
            plans = plan_jobs(
                venues,
                last_success,
                now,
                horizon_days=horizon_days,
                providers={provider},
                sports=sport_filter,
            )
            written = enqueue_jobs(engine, plans, dry_run=dry_run)
            total += written
            logging.info(
                f"{provider}: {len(venues)} venue(s), {len(plans)} planned job(s), "
                f"{written} written{' (dry run)' if dry_run else ''}"
            )
        logging.success(
            f"Scheduler enqueue complete: {total} job(s) "
            f"{'would be written' if dry_run else 'written'}"
        )
        return total


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue due crawl jobs into PostgreSQL"
    )
    parser.add_argument(
        "--provider",
        help="Comma-separated provider keys (default: all registered providers)",
    )
    parser.add_argument(
        "--sport",
        help="Comma-separated sports to enqueue (default: every sport a venue offers)",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=DEFAULT_HORIZON_DAYS,
        help=f"Days ahead to schedule, 1 to {DEFAULT_HORIZON_DAYS}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned jobs without writing to the database",
    )
    args = parser.parse_args(argv)
    run_enqueue(
        default_engine,
        providers=_csv(args.provider),
        sports=_csv(args.sport),
        horizon_days=args.horizon_days,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
