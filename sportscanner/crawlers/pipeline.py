import argparse
import asyncio
import itertools
import sys
from datetime import date, datetime, timedelta
from typing import Any, List, Optional, Tuple, Union

from sportscanner.logger import logging
from rich import print

from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema

from sportscanner.crawlers.parsers.better.badminton.scraper import (
    coroutines as BetterLeisureBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.activelambeth.badminton.scraper import (
    coroutines as ActiveLambethBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.citysports.badminton.scraper import (
    coroutines as CitySportsBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.everyoneactive.badminton.scraper import (
    coroutines as EveryoneActiveBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.towerhamlets.badminton.scraper import (
    coroutines as TowerHamletsBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.southwarkleisure.badminton.scraper import (
    coroutines as SouthwarkLeisureBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.haringey.badminton.scraper import (
    coroutines as HaringeyCouncilBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.uelsportsdock.badminton.scraper import (
    coroutines as UELSportsDockBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.placesleisure.badminton.scraper import (
    coroutines as PlacesLeisureBadmintonScraperCoroutines,
)

from sportscanner.crawlers.parsers.better.squash.scraper import (
    coroutines as BetterLeisureSquashScraperCoroutines,
)
from sportscanner.crawlers.parsers.activelambeth.squash.scraper import (
    coroutines as ActiveLambethSquashScraperCoroutines,
)
from sportscanner.crawlers.parsers.everyoneactive.squash.scraper import (
    coroutines as EveryoneActiveSquashScraperCoroutines,
)
from sportscanner.crawlers.parsers.visionrcl.squash.scraper import (
    coroutines as VisionRclSquashScraperCoroutines,
)
from sportscanner.crawlers.parsers.mytimeactive.squash.scraper import (
    coroutines as MytimeActiveSquashScraperCoroutines,
)

from sportscanner.crawlers.parsers.better.pickleball.scraper import (
    coroutines as BetterLeisurePickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.southwarkleisure.pickleball.scraper import (
    coroutines as SouthwarkLeisurePickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.decathlon.pickleball.scraper import (
    coroutines as DecathlonPickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.placesleisure.pickleball.scraper import (
    coroutines as PlacesLeisurePickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.placesleisure.core.strategy import (
    pacing_summary as places_leisure_pacing_summary,
)
from sportscanner.crawlers.parsers.playtomic.pickleball.scraper import (
    coroutines as PlaytomicPickleballScraperCoroutines,
)
from sportscanner.crawlers.parsers.courtreserve.pickleball.scraper import (
    coroutines as CourtReservePickleballScraperCoroutines,
)

from sportscanner.crawlers.parsers.matchi.padel.scraper import (
    coroutines as MatchiPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.playtomic.padel.scraper import (
    coroutines as PlaytomicPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.padelmates.padel.scraper import (
    coroutines as PadelMatesPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.stratfordpadel.padel.scraper import (
    coroutines as StratfordPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.matchpoint.padel.scraper import (
    coroutines as MatchpointPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.gladstonego.padel.scraper import (
    coroutines as GladstoneGoPadelScraperCoroutines,
)
from sportscanner.crawlers.parsers.clubspark.padel.scraper import (
    coroutines as ClubSparkPadelScraperCoroutines,
)

from sportscanner.crawlers.parsers.clubspark.tennis.scraper import (
    coroutines as ClubSparkTennisScraperCoroutines,
)
from sportscanner.crawlers.parsers.better.tennis.scraper import (
    coroutines as BetterLeisureTennisScraperCoroutines,
)
from sportscanner.crawlers.parsers.playtomic.tennis.scraper import (
    coroutines as PlaytomicTennisScraperCoroutines,
)
from sportscanner.crawlers.parsers.matchi.tennis.scraper import (
    coroutines as MatchiTennisScraperCoroutines,
)

from sportscanner.crawlers.parsers.visionrcl.badminton.scraper import (
    coroutines as VisionRclBadmintonScraperCoroutines,
)
from sportscanner.crawlers.parsers.mytimeactive.badminton.scraper import (
    coroutines as MytimeActiveBadmintonScraperCoroutines,
)


from sportscanner.storage.postgres.database import (
    insert_records_to_table,
    truncate_by_composite_key_and_reload,
    delete_past_slots,
    snapshot_slot_history,
)
from sportscanner.storage.postgres.tables import (
    BadmintonMasterTable,
    PickleballMasterTable,
    SquashMasterTable,
    PadelMasterTable,
    TennisMasterTable,
)
from sportscanner.utils import timeit
from sportscanner.variables import settings


def record_slot_history(TableForLoading, run_started: datetime) -> None:
    """Feeds the market insights. Best-effort: a history failure must never fail
    the crawl that keeps search results fresh."""
    try:
        snapshot_slot_history(TableForLoading, refreshed_since=run_started)
    except Exception as exc:
        logging.error(
            f"slot_history snapshot failed for {TableForLoading.__tablename__}: {exc!r}"
        )


def flatten_responses(responses_from_all_sources) -> List[UnifiedParserSchema]:
    _validation_check: List[UnifiedParserSchema] = [
        slot for response in responses_from_all_sources if response for slot in response
    ]
    if not all(isinstance(slot, UnifiedParserSchema) for slot in _validation_check):
        raise TypeError(
            "One or more elements in `_validation_check` are not of type: `UnifiedParserSchema`"
        )
    return _validation_check


# Some providers (Everyone Active squash, CourtReserve games, Stratford Padel,
# Mytime Active) do not expose pricing in their availability payloads at all,
# so their slots used to ship with a blank or "N/A" price. The frontend then
# shows nothing where the price chip should be. This filler derives an
# estimate from the prices that ARE known: per venue (composite_key) first,
# falling back to a per-sport median, and stamps estimates with a "~" prefix
# so the UI can distinguish them from confirmed prices.
_DEFAULT_ESTIMATED_PRICE_PER_SPORT = {
    "Badminton": 13.00,
    "Squash": 12.00,
    "Pickleball": 8.00,
    "Padel": 20.00,
    "Tennis": 12.00,
}


def _parse_price(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    cleaned = value.replace("£", "").replace("~", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def fill_estimated_prices(
    slots: List[UnifiedParserSchema],
) -> List[UnifiedParserSchema]:
    """Fills blank / "N/A" prices with an estimated figure derived from known
    prices for the same venue (composite_key), falling back to the same sport's
    median, then a per-sport default. Estimates are prefixed with "~"."""
    known_by_venue: dict = {}
    known_by_sport: dict = {}
    for slot in slots:
        price = _parse_price(slot.price)
        if price is None:
            continue
        known_by_venue.setdefault(slot.composite_key, []).append(price)
        known_by_sport.setdefault(slot.category, []).append(price)

    def _median(values: List[float]) -> float:
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    median_by_venue = {k: _median(v) for k, v in known_by_venue.items()}
    median_by_sport = {k: _median(v) for k, v in known_by_sport.items()}

    filled = 0
    for slot in slots:
        if _parse_price(slot.price) is not None:
            continue
        if slot.composite_key in median_by_venue:
            estimate = median_by_venue[slot.composite_key]
        elif slot.category in median_by_sport:
            estimate = median_by_sport[slot.category]
        else:
            estimate = _DEFAULT_ESTIMATED_PRICE_PER_SPORT.get(slot.category, 10.00)
        slot.price = f"~£{estimate:.2f}"
        filled += 1
    if filled:
        logging.info(
            f"Estimated prices filled for {filled} slot(s) with no pricing data"
        )
    return slots


@timeit
def badminton_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    run_started = datetime.now()
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(10)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_for_upsertion: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            BetterLeisureBadmintonScraperCoroutines(dates),
            ActiveLambethBadmintonScraperCoroutines(dates),
            CitySportsBadmintonScraperCoroutines(dates),
            EveryoneActiveBadmintonScraperCoroutines(dates),
            SouthwarkLeisureBadmintonScraperCoroutines(dates),
            HaringeyCouncilBadmintonScraperCoroutines(dates),
            UELSportsDockBadmintonScraperCoroutines(dates),
            # Places Leisure runs as its own slower job (see
            # places_leisure_scraping_pipeline below and
            # .github/workflows/places-leisure-pipeline.yml). Its per-timeslot
            # availability API needs ~1,500 paced requests for a 10 day window,
            # which cannot fit this pipeline's 15 minute budget.
            VisionRclBadmintonScraperCoroutines(dates),
            MytimeActiveBadmintonScraperCoroutines(dates),
        )
    )
    responses_for_reload: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(TowerHamletsBadmintonScraperCoroutines(dates))
    )

    # Flatten nested list structure and remove empty or failed responses
    flattened_responses_for_upsertion: List[UnifiedParserSchema] = (
        fill_estimated_prices(flatten_responses(responses_for_upsertion))
    )
    flattened_responses_for_reload: List[UnifiedParserSchema] = fill_estimated_prices(
        flatten_responses(responses_for_reload)
    )

    # Housekeeping: drop past-date rows so the table doesn't grow unbounded over time.
    delete_past_slots(BadmintonMasterTable)

    if flattened_responses_for_upsertion or flattened_responses_for_reload:
        logging.success(
            f"Total slots collected for Upsert: {len(flattened_responses_for_upsertion)}"
        )
        logging.success(
            f"Total slots collected for Reload: {len(flattened_responses_for_reload)}"
        )
        logging.info(
            f"Upserting all data to master table: {BadmintonMasterTable.__tablename__}"
        )
        insert_records_to_table(flattened_responses_for_upsertion, BadmintonMasterTable)
        logging.info(
            f"Reloading all data to master table: {BadmintonMasterTable.__tablename__}"
        )
        truncate_by_composite_key_and_reload(
            flattened_responses_for_reload, BadmintonMasterTable
        )
        record_slot_history(BadmintonMasterTable, run_started)
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def squash_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    run_started = datetime.now()
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(15)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            BetterLeisureSquashScraperCoroutines(dates),
            ActiveLambethSquashScraperCoroutines(dates),
            EveryoneActiveSquashScraperCoroutines(dates),
            VisionRclSquashScraperCoroutines(dates),
            MytimeActiveSquashScraperCoroutines(dates),
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = fill_estimated_prices(
        flatten_responses(responses_from_all_sources)
    )
    # Housekeeping: drop past-date rows so the table doesn't grow unbounded over time.
    delete_past_slots(SquashMasterTable)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        logging.info(
            f"Upserting all data to master table: {SquashMasterTable.__tablename__}"
        )
        insert_records_to_table(all_slots, SquashMasterTable)
        record_slot_history(SquashMasterTable, run_started)
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def pickleball_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    run_started = datetime.now()
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(15)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            BetterLeisurePickleballScraperCoroutines(dates),
            SouthwarkLeisurePickleballScraperCoroutines(dates),
            DecathlonPickleballScraperCoroutines(dates),
            # Places Leisure runs as its own slower job - same provider, same
            # per-timeslot fan-out as the badminton pipeline.
            PlaytomicPickleballScraperCoroutines(dates),
            CourtReservePickleballScraperCoroutines(dates),
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = fill_estimated_prices(
        flatten_responses(responses_from_all_sources)
    )
    # Housekeeping: drop past-date rows so the table doesn't grow unbounded over time.
    delete_past_slots(PickleballMasterTable)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        logging.info(
            f"Upserting all data to master table: {PickleballMasterTable.__tablename__}"
        )
        insert_records_to_table(all_slots, PickleballMasterTable)
        record_slot_history(PickleballMasterTable, run_started)
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def padel_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    run_started = datetime.now()
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(10)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            MatchiPadelScraperCoroutines(dates),
            PlaytomicPadelScraperCoroutines(dates),
            PadelMatesPadelScraperCoroutines(dates),
            StratfordPadelScraperCoroutines(dates),
            MatchpointPadelScraperCoroutines(dates),
            GladstoneGoPadelScraperCoroutines(dates),
            ClubSparkPadelScraperCoroutines(dates),
        )
    )
    all_slots: List[UnifiedParserSchema] = fill_estimated_prices(
        flatten_responses(responses_from_all_sources)
    )
    # Housekeeping: drop past-date rows so the table doesn't grow unbounded over time.
    delete_past_slots(PadelMasterTable)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        logging.info(
            f"Upserting all data to master table: {PadelMasterTable.__tablename__}"
        )
        insert_records_to_table(all_slots, PadelMasterTable)
        record_slot_history(PadelMasterTable, run_started)
        return True
    else:
        logging.warning(
            "No valid padel slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def tennis_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    run_started = datetime.now()
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(10)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            ClubSparkTennisScraperCoroutines(dates),
            BetterLeisureTennisScraperCoroutines(dates),
            PlaytomicTennisScraperCoroutines(dates),
            MatchiTennisScraperCoroutines(dates),
        )
    )
    all_slots: List[UnifiedParserSchema] = fill_estimated_prices(
        flatten_responses(responses_from_all_sources)
    )
    # Housekeeping: drop past-date rows so the table doesn't grow unbounded over time.
    delete_past_slots(TennisMasterTable)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        logging.info(
            f"Upserting all data to master table: {TennisMasterTable.__tablename__}"
        )
        insert_records_to_table(all_slots, TennisMasterTable)
        record_slot_history(TennisMasterTable, run_started)
        return True
    else:
        logging.warning(
            "No valid tennis slots were found. Database update skipped (might be an issue)"
        )
        return False


# Places Leisure cannot join the fast pipelines: its availability API is one
# request per distinct scheduled timeslot (confirmed live 2026-10-28 - no bulk
# mode, and the embedded schedule carries no availability data), so a 10 day
# badminton window is ~1,500 paced requests, ~76 minutes at the WAF-safe 3s
# interval. Three days keeps a dedicated run around 45 minutes for both sports
# while still covering everything a player can book this week.
_PLACES_LEISURE_HORIZON_DAYS = 3


@timeit
def places_leisure_scraping_pipeline():
    """Slow, low-frequency refresh for Places Leisure only.

    Runs both sports in one process and one event loop so they share the
    provider's single rate limiter (`_paced_get` in
    placesleisure/core/strategy.py). The pacer serialises the availability
    calls, so the sports interleave rather than each getting its own 3s budget.
    Two parallel containers would double the real request rate against the same
    egress IP, which is what the 2026-08-30 outage looked like.
    """
    logging.warning(f"Running Places Leisure refresh for environment: `{settings.ENV}`")
    run_started = datetime.now()
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(_PLACES_LEISURE_HORIZON_DAYS)]
    logging.info(f"Finding Places Leisure slots for dates: {dates}")

    completed = True

    async def _crawl_both():
        return await SportscannerCrawlerBot(
            PlacesLeisureBadmintonScraperCoroutines(dates),
            PlacesLeisurePickleballScraperCoroutines(dates),
        )

    # One event loop for both sports. The provider's rate limiter
    # (`_rate_limiter_lock` / `_pacer` in placesleisure/core/strategy.py)
    # is a module-level asyncio primitive, so a second asyncio.run() in the same
    # process rebinds it to a new loop and every request fails with "bound to a
    # different event loop".
    responses = asyncio.run(_crawl_both())
    logging.info(f"Places Leisure pacing settled at {places_leisure_pacing_summary()}")

    targets = (
        ("badminton", responses[0], BadmintonMasterTable),
        ("pickleball", responses[1], PickleballMasterTable),
    )
    for label, response, master_table in targets:
        all_slots: List[UnifiedParserSchema] = fill_estimated_prices(
            [slot for slot in response if slot]
        )
        if not all_slots:
            logging.warning(
                f"Places Leisure {label}: no slots returned, table left untouched"
            )
            completed = False
            continue
        logging.success(f"Places Leisure {label}: {len(all_slots)} slot(s) collected")
        insert_records_to_table(all_slots, master_table)
        record_slot_history(master_table, run_started)
    return completed


if __name__ == "__main__":
    """Gathers data from all sources/providers and loads to SQL database"""

    parser = argparse.ArgumentParser(description="Run SportScanner scraping pipelines")
    parser.add_argument(
        "--task",
        choices=[
            "badminton",
            "squash",
            "pickleball",
            "padel",
            "tennis",
            "placesleisure",
            "all",
        ],
        required=False,
        help="Which pipeline to run",
    )
    args = parser.parse_args()

    if args.task == "badminton":
        logging.info("Starting Badminton scraping pipeline...")
        badminton_scraping_pipeline()
    elif args.task == "squash":
        logging.info("Starting Squash scraping pipeline...")
        squash_scraping_pipeline()
    elif args.task == "pickleball":
        logging.info("Starting Pickleball scraping pipeline...")
        pickleball_scraping_pipeline()
    elif args.task == "padel":
        logging.info("Starting Padel scraping pipeline...")
        padel_scraping_pipeline()
    elif args.task == "tennis":
        logging.info("Starting Tennis scraping pipeline...")
        tennis_scraping_pipeline()
    elif args.task == "placesleisure":
        logging.info("Starting Places Leisure scraping pipeline...")
        # Exit non-zero on a partial or empty run so the dedicated workflow
        # goes red instead of leaving a silent hole in badminton/pickleball.
        sys.exit(0 if places_leisure_scraping_pipeline() else 1)
    else:
        logging.info("Starting ALL scraping pipelines...")
        badminton_scraping_pipeline()
        squash_scraping_pipeline()
        pickleball_scraping_pipeline()
        padel_scraping_pipeline()
        tennis_scraping_pipeline()
