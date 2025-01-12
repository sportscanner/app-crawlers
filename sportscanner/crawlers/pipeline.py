import time
import uuid
from datetime import date, timedelta
from typing import List, Union, Any
import asyncio
from loguru import logger as logging
from rich import print
from sqlmodel import Session
import itertools

from sportscanner.crawlers.database import (
    PipelineRefreshStatus,
    SportScanner,
    delete_all_items_and_insert_fresh_to_db,
    engine,
    get_refresh_status_for_pipeline,
    initialize_db_and_tables,
    pipeline_refresh_decision_based_on_interval,
    update_refresh_status_for_pipeline,
    get_all_sports_venues, SportsVenue
)
from sportscanner.crawlers.parsers.better import crawler as BetterOrganisation
from sportscanner.crawlers.parsers.citysports import crawler as CitySports
from sportscanner.crawlers.parsers.schema import UnifiedParserSchema
from sportscanner.crawlers.utils import (
    find_consecutive_slots,
    format_consecutive_slots_groupings,
    timeit,
)


async def SportscannerCrawlerBot(*coroutine_lists: Union[List[Any], Any]) -> List[UnifiedParserSchema]:
    # Normalize inputs: wrap single coroutines in a list
    normalized_inputs = [
        coro_list if isinstance(coro_list, list) else [coro_list]
        for coro_list in coroutine_lists
    ]

    # Flatten the coroutine lists and filter out invalid inputs
    coroutines = [coro for coro_list in normalized_inputs for coro in coro_list]

    # Ensure all inputs are valid coroutines
    assert all(asyncio.iscoroutine(c) for c in coroutines), "Invalid coroutine in input"

    if not coroutines:
        return []

    # Run only non-empty coroutines with asyncio.gather
    return await asyncio.gather(*coroutines)


@timeit
def full_data_refresh_pipeline(sports_venues: List[SportsVenue]):
    update_refresh_status_for_pipeline(engine, PipelineRefreshStatus.RUNNING)
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(2)]
    logging.info(f"Finding slots for dates: {dates}")
    sports_venues = get_all_sports_venues(engine)
    venues_slugs = [sports_venue.slug for sports_venue in sports_venues]
    BetterOrganisationCrawlerCoroutines = BetterOrganisation.pipeline(dates, venues_slugs)
    CitySportsCrawlerCoroutines = CitySports.pipeline(dates, venues_slugs)

    responses_from_all_sources: Tuple[List[UnifiedParserSchema], ...] = asyncio.run(
        SportscannerCrawlerBot(
            BetterOrganisationCrawlerCoroutines,
            CitySportsCrawlerCoroutines
        )
    )
    # Flattened 3-layer deep list nestings
    all_slots = list(itertools.chain.from_iterable(itertools.chain.from_iterable(responses_from_all_sources)))
    delete_all_items_and_insert_fresh_to_db(all_slots)
    update_refresh_status_for_pipeline(engine, PipelineRefreshStatus.COMPLETED)


@timeit
async def standalone_refresh_trigger(dates: List[date], venues_slugs: List[str]) -> List[UnifiedParserSchema]:
    logging.info(f"Finding slots for dates: {dates}")
    BetterOrganisationCrawlerCoroutines = BetterOrganisation.pipeline(dates, venues_slugs)
    CitySportsCrawlerCoroutines = CitySports.pipeline(dates, venues_slugs)

    all_fetched_slots = await SportscannerCrawlerBot(
        BetterOrganisationCrawlerCoroutines,
        CitySportsCrawlerCoroutines
    )
    all_slots: List[UnifiedParserSchema] = list(itertools.chain.from_iterable(itertools.chain.from_iterable(all_fetched_slots)))
    return all_slots


def main():
    """Gathers data from all sources/providers and loads to SQL database"""
    full_data_refresh_pipeline()


if __name__ == "__main__":
    main()
