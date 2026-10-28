import os
import uuid

import pytest
from sqlalchemy import text

from sportscanner.variables import settings


def scheduler_db_enabled() -> bool:
    return os.getenv("RUN_SCHEDULER_DB_TESTS") == "1"


@pytest.fixture(scope="session")
def scheduler_engine():
    if not scheduler_db_enabled():
        pytest.skip("Set RUN_SCHEDULER_DB_TESTS=1 to run scheduler database tests")
    if settings.ENV == "prod":
        pytest.skip("Scheduler database tests must not run against production")

    from sportscanner.storage.postgres.database import engine
    from sportscanner.storage.postgres.tables import CrawlJob, CrawlSourceStatus

    CrawlJob.__table__.create(bind=engine, checkfirst=True)
    CrawlSourceStatus.__table__.create(bind=engine, checkfirst=True)
    return engine


@pytest.fixture()
def queue_prefix(scheduler_engine):
    prefix = f"scheduler-test-{uuid.uuid4().hex[:8]}"
    yield prefix
    with scheduler_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.crawl_job WHERE provider LIKE :prefix"),
            {"prefix": prefix + "%"},
        )
        conn.execute(
            text("DELETE FROM public.crawl_source_status WHERE provider LIKE :prefix"),
            {"prefix": prefix + "%"},
        )


@pytest.fixture()
def padel_venue_key(scheduler_engine):
    with scheduler_engine.connect() as conn:
        key = conn.execute(
            text(
                "SELECT composite_key FROM public.sportsvenue "
                "WHERE 'padel' = ANY(sports) LIMIT 1"
            )
        ).scalar()
    if key is None:
        pytest.skip("No padel venue in the development database")
    return key
