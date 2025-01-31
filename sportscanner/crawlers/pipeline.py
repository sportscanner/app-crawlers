import asyncio
import itertools
from datetime import date, timedelta
from typing import Any, List, Tuple, Union

from loguru import logger as logging
from prefect.tasks import task_input_hash
from rich import print
from ruamel.yaml.tag import tag_attrib

from sportscanner.crawlers.parsers.better import crawler as BetterOrganisation
from sportscanner.crawlers.parsers.citysports import crawler as CitySports
from sportscanner.crawlers.parsers.playground import crawler as Playground
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.storage.postgres.database import (
    PipelineRefreshStatus,
    delete_all_items_and_insert_fresh_to_db,
    engine,
    get_all_sports_venues,
    update_refresh_status_for_pipeline,
)
from sportscanner.utils import timeit
from sportscanner.crawlers.helpers import SportscannerCrawlerBot
from prefect import flow, get_run_logger, task


@task
def flatten_responses(responses_from_all_sources):
    _tmp = [
        slot for response in responses_from_all_sources if response for slot in response
    ]
    raise Exception("Temporary blocking")
    return _tmp

@flow(name="Srapper pipeline", description="All coroutines launched from here")
@timeit
def full_data_refresh_pipeline():
    logging = get_run_logger()
    update_refresh_status_for_pipeline(engine, PipelineRefreshStatus.RUNNING)
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(1)]
    logging.info(f"Finding slots for dates: {dates}")
    sports_venues = get_all_sports_venues(engine)[:10]
    venues_slugs = [sports_venue.slug for sports_venue in sports_venues]
    BetterOrganisationCrawlerCoroutines = BetterOrganisation.pipeline(
        dates, venues_slugs
    )
    CitySportsCrawlerCoroutines = CitySports.pipeline(dates, venues_slugs)
    PlaygroundCrawlerCoroutines = Playground.pipeline(dates, venues_slugs)

    responses_from_all_sources: Tuple[List[UnifiedParserSchema], ...] = asyncio.run(
        SportscannerCrawlerBot(
            BetterOrganisationCrawlerCoroutines,
            CitySportsCrawlerCoroutines,
            # PlaygroundCrawlerCoroutines
        )
    )
    # Flatten nested list structure and remove empty or failed responses
    all_slots: List[UnifiedParserSchema] = flatten_responses(responses_from_all_sources)
    # Check if the final list has valid entries
    if not all_slots:
        logging.warning("No valid slots were found. Exiting pipeline.")
    else:
        logging.info(f"Total slots collected: {len(all_slots)}")
    delete_all_items_and_insert_fresh_to_db(all_slots)
    update_refresh_status_for_pipeline(engine, PipelineRefreshStatus.COMPLETED)
    return True


@timeit
async def standalone_refresh_trigger(
    dates: List[date], venues_slugs: List[str]
) -> List[UnifiedParserSchema]:
    logging.info(f"Finding slots for dates: {dates}")
    BetterOrganisationCrawlerCoroutines = BetterOrganisation.pipeline(
        dates, venues_slugs
    )
    CitySportsCrawlerCoroutines = CitySports.pipeline(dates, venues_slugs)

    all_fetched_slots = await SportscannerCrawlerBot(
        BetterOrganisationCrawlerCoroutines, CitySportsCrawlerCoroutines
    )
    all_slots: List[UnifiedParserSchema] = list(
        itertools.chain.from_iterable(itertools.chain.from_iterable(all_fetched_slots))
    )
    return all_slots


if __name__ == "__main__":
    """Gathers data from all sources/providers and loads to SQL database"""
    full_data_refresh_pipeline()
