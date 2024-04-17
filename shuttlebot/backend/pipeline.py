from loguru import logger as logging
import uuid
from rich import print
from typing import List
from datetime import date, timedelta
from shuttlebot.backend.parsers.better import api as BetterOrganisation
from shuttlebot.backend.parsers.citysports import api as CitySports
from shuttlebot.backend.utils import (timeit, find_consecutive_slots,
                                      format_consecutive_slots_groupings)
from shuttlebot.backend.database import (engine, SportScanner,
                                         delete_and_insert_slots_to_database,
                                         initialize_db_and_tables,
                                         get_refresh_status_for_pipeline,
                                         update_refresh_status_for_pipeline,
                                         pipeline_refresh_decision_based_on_interval,
                                         PipelineRefreshStatus)
from sqlmodel import Session
import time


def pipeline_data_refresh():
    update_refresh_status_for_pipeline(engine, PipelineRefreshStatus.RUNNING)
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(6)]
    logging.info(f"Finding slots for dates: {dates}")

    logging.debug(f"Fetching data for org: 'better.org.uk' - hash: "
                  f"'817c4e0f86723d52f14291327ca1723dc00a8615'")
    slots_fetched_org_hash_817c4e0f86723d52f14291327ca1723dc00a8615 = BetterOrganisation.pipeline(
        dates)
    logging.info("Delete/Insert slots for org: 817c4e0f86723d52f14291327ca1723dc00a8615")
    delete_and_insert_slots_to_database(
        slots_fetched_org_hash_817c4e0f86723d52f14291327ca1723dc00a8615,
        organisation="better.org.uk"
    )

    logging.debug(f"Fetching data for org: 'citysport.org.uk' - hash: "
                  f"'378b041c5cd6e6844e173b295b62f259f78189b1'")
    slots_fetched_org_hash_378b041c5cd6e6844e173b295b62f259f78189b1 = CitySports.pipeline(dates)
    logging.info("Delete/Insert slots for org: 378b041c5cd6e6844e173b295b62f259f78189b1")
    delete_and_insert_slots_to_database(
        slots_fetched_org_hash_378b041c5cd6e6844e173b295b62f259f78189b1,
        organisation="citysport.org.uk"
    )

    update_refresh_status_for_pipeline(engine, PipelineRefreshStatus.COMPLETED)


@timeit
def main():
    """Gathers data from all sources/providers and loads to SQL database"""
    initialize_db_and_tables(engine)
    pipeline_refresh_decision_based_on_interval(engine, timedelta(minutes=30))
    while get_refresh_status_for_pipeline(engine) != PipelineRefreshStatus.COMPLETED.value:
        if get_refresh_status_for_pipeline(engine) == PipelineRefreshStatus.OBSOLETE.value:
            pipeline_data_refresh()
        elif get_refresh_status_for_pipeline(engine) == PipelineRefreshStatus.RUNNING.value:
            logging.info("Pipeline is currently running, wait for data refresh")
            time.sleep(2)

    consecutive_slots: List[List[SportScanner]] = find_consecutive_slots(5)
    format_consecutive_slots_groupings(consecutive_slots)


if __name__ == "__main__":
    main()
