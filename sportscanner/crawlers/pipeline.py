import asyncio
import itertools
from datetime import date, timedelta
from math import lgamma
from typing import Any, List, Tuple, Union

from loguru import logger as logging
from rich import print

from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema

from sportscanner.crawlers.parsers.better.badminton.scraper import coroutines as BetterLeisureBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.activelambeth.badminton.scraper import coroutines as ActiveLambethBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.citysports.badminton.scraper import coroutines as CitySportsBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.everyoneactive.badminton.scraper import coroutines as EveryoneActiveBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.towerhamlets.badminton.scraper import coroutines as TowerHamletsBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.southwarkleisure.badminton.scraper import coroutines as SouthwarkLeisureBadmintonScraperCoroutines

from sportscanner.crawlers.parsers.better.squash.scraper import coroutines as BetterLeisureSquashScraperCoroutines
from sportscanner.crawlers.parsers.activelambeth.squash.scraper import coroutines as ActiveLambethSquashScraperCoroutines

from sportscanner.storage.postgres.database import (
truncate_and_reload_all, BadmintonStagingTable, swap_tables,
    initialise_squash_staging, initialise_badminton_staging
)
from sportscanner.storage.postgres.tables import SquashStagingTable
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


@timeit
def badminton_scraping_pipeline():
    logging.warning(f"Running data refresh for environment: `{settings.ENV}`")
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(15)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            BetterLeisureBadmintonScraperCoroutines(dates),
            ActiveLambethBadmintonScraperCoroutines(dates),
            CitySportsBadmintonScraperCoroutines(dates),
            EveryoneActiveBadmintonScraperCoroutines(dates),
            TowerHamletsBadmintonScraperCoroutines(dates),
            SouthwarkLeisureBadmintonScraperCoroutines(dates)
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = flatten_responses(responses_from_all_sources)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        initialise_badminton_staging()
        logging.info(f"Truncating and loading all data to staging table: {BadmintonStagingTable.__tablename__}")
        truncate_and_reload_all(all_slots, BadmintonStagingTable)
        logging.warning(f"Swapping staging table, with Main table")
        swap_tables(master = "badminton", staging = "staging.badminton", archive = "archive.badminton")
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
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = flatten_responses(responses_from_all_sources)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        initialise_squash_staging()
        logging.info(f"Truncating and loading all data to staging table: {SquashStagingTable.__tablename__}")
        truncate_and_reload_all(all_slots, SquashStagingTable)
        logging.warning(f"Swapping staging table, with Main table")
        swap_tables(master = "squash", staging = "staging.squash", archive = "archive.squash")
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


if __name__ == "__main__":
    """Gathers data from all sources/providers and loads to SQL database"""
    # squash_scraping_pipeline()
    badminton_scraping_pipeline()
