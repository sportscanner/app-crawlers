import argparse
import asyncio
import itertools
from datetime import date, timedelta
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
            # Places Leisure temporarily disabled (2026-08-30): its per-timeslot
            # availability API structurally cannot fit this pipeline's normal
            # 1-2 minute runtime - even at a WAF-safe pacing (confirmed
            # necessary: unpaced/lightly-paced requests get 429'd), 8 venues x
            # hundreds of distinct scheduled slots each serializes to tens of
            # minutes, which stacked overlapping pipeline runs and took down
            # the production search API. Re-enable only alongside a real
            # architectural fix (e.g. running it as its own slower, less
            # frequent job outside this fast pipeline), not just a smaller
            # pacing constant.
            # PlacesLeisureBadmintonScraperCoroutines(dates),
            VisionRclBadmintonScraperCoroutines(dates),
            MytimeActiveBadmintonScraperCoroutines(dates),
        )
    )
    responses_for_reload: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(TowerHamletsBadmintonScraperCoroutines(dates))
    )

    # Flatten nested list structure and remove empty or failed responses
    flattened_responses_for_upsertion: List[UnifiedParserSchema] = fill_estimated_prices(
        flatten_responses(responses_for_upsertion)
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
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def squash_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
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
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def pickleball_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(15)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            BetterLeisurePickleballScraperCoroutines(dates),
            SouthwarkLeisurePickleballScraperCoroutines(dates),
            DecathlonPickleballScraperCoroutines(dates),
            # Places Leisure temporarily disabled - see the badminton pipeline
            # above for why (same provider, same structural issue).
            # PlacesLeisurePickleballScraperCoroutines(dates),
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
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def padel_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(10)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            MatchiPadelScraperCoroutines(dates),
            PlaytomicPadelScraperCoroutines(dates),
            PadelMatesPadelScraperCoroutines(dates),
            StratfordPadelScraperCoroutines(dates),
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
        return True
    else:
        logging.warning(
            "No valid padel slots were found. Database update skipped (might be an issue)"
        )
        return False


@timeit
def tennis_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
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
        return True
    else:
        logging.warning(
            "No valid tennis slots were found. Database update skipped (might be an issue)"
        )
        return False


if __name__ == "__main__":
    """Gathers data from all sources/providers and loads to SQL database"""

    parser = argparse.ArgumentParser(description="Run SportScanner scraping pipelines")
    parser.add_argument(
        "--task",
        choices=["badminton", "squash", "pickleball", "padel", "tennis", "all"],
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
    else:
        logging.info("Starting ALL scraping pipelines...")
        badminton_scraping_pipeline()
        squash_scraping_pipeline()
        pickleball_scraping_pipeline()
        padel_scraping_pipeline()
        tennis_scraping_pipeline()
