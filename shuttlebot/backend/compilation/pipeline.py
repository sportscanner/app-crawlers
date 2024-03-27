from loguru import logger as logging
import uuid

from shuttlebot.backend.parsers.better import api as BetterOrganisation
from shuttlebot.backend.utils import timeit
from shuttlebot.backend.database import engine, SportScanner, delete_and_insert_slots_to_database
from sqlmodel import Session

@timeit
def main():
    """Gathers data from all sources/providers and loads to SQL database"""
    logging.debug(f"Fetching data for org: 'better.org.uk' - hash: "
                  f"'817c4e0f86723d52f14291327ca1723dc00a8615'")
    slots_fetched_org_hash_817c4e0f86723d52f14291327ca1723dc00a8615 = BetterOrganisation.pipeline()
    logging.info("Delete/Insert slots for org: 817c4e0f86723d52f14291327ca1723dc00a8615")
    delete_and_insert_slots_to_database(
        slots_fetched_org_hash_817c4e0f86723d52f14291327ca1723dc00a8615,
        organisation="better.org.uk"
    )


if __name__ == "__main__":
    main()
