from loguru import logger as logging
import uuid
from datetime import date, timedelta
from shuttlebot.backend.parsers.better import api as BetterOrganisation
from shuttlebot.backend.parsers.citysports import api as CitySports
from shuttlebot.backend.utils import timeit
from shuttlebot.backend.database import delete_and_insert_slots_to_database
from sqlmodel import Session

@timeit
def main():
    """Gathers data from all sources/providers and loads to SQL database"""
    today = date.today()
    dates = [today + timedelta(days=i) for i in range(2)]
    logging.info(f"Finding slots for dates: {dates}")

    logging.debug(f"Fetching data for org: 'better.org.uk' - hash: "
                  f"'817c4e0f86723d52f14291327ca1723dc00a8615'")
    slots_fetched_org_hash_817c4e0f86723d52f14291327ca1723dc00a8615 = BetterOrganisation.pipeline(dates)
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


if __name__ == "__main__":
    main()
