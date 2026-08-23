"""
Padel Mates padel scraper.

Standard BaseCrawler loop: the availability API is one request per (venue,
date), so only a request strategy + response parser are supplied and
BaseCrawler owns the fetch/concurrency/error handling.

Usage (pipeline):
    coroutines(search_dates)  ->  coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.padelmates.padel.scraper
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Coroutine, List

from sportscanner.storage.postgres.tables import SportsVenue
from sportscanner.crawlers.parsers.core.interfaces import BaseCrawler
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.padelmates.core.strategy import (
    PadelMatesRequestStrategy,
    PadelMatesResponseParserStrategy,
    PADEL_MATES_ORGANISATION_WEBSITE,
)
from sportscanner.logger import logging
from sportscanner.utils import async_timer


class PadelMatesPadelCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=PadelMatesRequestStrategy(),
            response_parser_strategy=PadelMatesResponseParserStrategy(),
            organisation_website=PADEL_MATES_ORGANISATION_WEBSITE,
        )


def coroutines(
    search_dates: List[date],
) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py. delta=6 keeps requests inside the platform's
    7-day booking window; dates beyond it 404 with "No active pricelist"."""
    return PadelMatesPadelCrawler().coroutines(search_dates, sport="padel", delta=6)


if __name__ == "__main__":
    from rich import print

    _dates = [date.today() + timedelta(days=1)]
    crawler = PadelMatesPadelCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="padel")
    if not venues:
        print(
            "[yellow]No Padel Mates venues in DB. Add entries to venues.json first.[/yellow]"
        )
    else:
        results = asyncio.run(crawler.ScraperCoroutines(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results[:20]:
            print(r)
