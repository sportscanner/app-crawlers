import argparse
import asyncio
import itertools
from datetime import date, timedelta
from math import lgamma
from typing import Any, List, Tuple, Union

from sportscanner.logger import logging
from rich import print

from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema

from sportscanner.crawlers.parsers.better.badminton.scraper import coroutines as BetterLeisureBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.activelambeth.badminton.scraper import coroutines as ActiveLambethBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.citysports.badminton.scraper import coroutines as CitySportsBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.everyoneactive.badminton.scraper import coroutines as EveryoneActiveBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.towerhamlets.badminton.scraper import coroutines as TowerHamletsBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.southwarkleisure.badminton.scraper import coroutines as SouthwarkLeisureBadmintonScraperCoroutines
from sportscanner.crawlers.parsers.haringey.badminton.scraper import coroutines as HaringeyCouncilBadmintonScraperCoroutines

from sportscanner.crawlers.parsers.better.squash.scraper import coroutines as BetterLeisureSquashScraperCoroutines
from sportscanner.crawlers.parsers.activelambeth.squash.scraper import coroutines as ActiveLambethSquashScraperCoroutines

from sportscanner.crawlers.parsers.better.pickleball.scraper import coroutines as BetterLeisurePickleballScraperCoroutines
from sportscanner.crawlers.parsers.southwarkleisure.pickleball.scraper import coroutines as SouthwarkLeisurePickleballScraperCoroutines
from sportscanner.crawlers.parsers.decathlon.pickleball.scraper import coroutines as DecathlonPickleballScraperCoroutines


from sportscanner.storage.postgres.database import (
insert_records_to_table, truncate_and_reload_all, swap_tables,
    initialise_squash_staging, initialise_badminton_staging, initialise_pickleball_staging
)
from sportscanner.storage.postgres.tables import BadmintonMasterTable, PickleballMasterTable, SquashMasterTable, SquashStagingTable, BadmintonStagingTable, PickleballStagingTable
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
    dates = [today + timedelta(days=i) for i in range(10)]
    logging.info(f"Finding slots for dates: {dates}")
    responses_from_all_sources: List[UnifiedParserSchema] = asyncio.run(
        SportscannerCrawlerBot(
            BetterLeisureBadmintonScraperCoroutines(dates),
            ActiveLambethBadmintonScraperCoroutines(dates),
            CitySportsBadmintonScraperCoroutines(dates),
            EveryoneActiveBadmintonScraperCoroutines(dates),
            TowerHamletsBadmintonScraperCoroutines(dates),
            SouthwarkLeisureBadmintonScraperCoroutines(dates),
            HaringeyCouncilBadmintonScraperCoroutines(dates)
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = flatten_responses(responses_from_all_sources)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        logging.info(f"Upserting all data to master table: {BadmintonMasterTable.__tablename__}")
        insert_records_to_table(all_slots, BadmintonMasterTable)
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
        logging.info(f"Upserting all data to master table: {SquashMasterTable.__tablename__}")
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
            DecathlonPickleballScraperCoroutines(dates)
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = flatten_responses(responses_from_all_sources)
    if all_slots:
        logging.success(f"Total slots collected: {len(all_slots)}")
        logging.info(f"Upserting all data to master table: {PickleballMasterTable.__tablename__}")
        insert_records_to_table(all_slots, PickleballMasterTable)
        return True
    else:
        logging.warning(
            "No valid slots were found. Database update skipped (might be an issue)"
        )
        return False


if __name__ == "__main__":
    """Gathers data from all sources/providers and loads to SQL database"""

    parser = argparse.ArgumentParser(description="Run SportScanner scraping pipelines")
    parser.add_argument(
        "--task",
        choices=["badminton", "squash", "pickleball", "all"],
        required=False,
        help="Which pipeline to run"
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
    else:
        logging.info("Starting ALL scraping pipelines...")
        badminton_scraping_pipeline()
        squash_scraping_pipeline()
        pickleball_scraping_pipeline()
