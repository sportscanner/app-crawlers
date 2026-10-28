"""
ClubSpark (LTA) Padel scraper.

Same public GetVenueSessions API as the tennis crawler, but the response parser
selects padel resources explicitly: Category 13 (ClubSpark's own Padel
category), plus an explicit resource-name fallback for the few venues whose
padel courts are filed under the tennis category (the LTA's PadelNTC account
is the known case). Tennis courts are never accepted as padel.

Usage (pipeline):
    coroutines(search_dates) -> coroutine yielding List[UnifiedParserSchema]

Direct run:
    python -m sportscanner.crawlers.parsers.clubspark.padel.scraper
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Coroutine, List

from rich import print

from sportscanner.crawlers.parsers.clubspark.core.strategy import (
    CLUBSPARK_ORGANISATION_WEBSITE,
    ClubSparkPadelRequestStrategy,
    ClubSparkPadelResponseParserStrategy,
)
from sportscanner.crawlers.parsers.clubspark.tennis.scraper import (
    ClubSparkTennisCrawler,
)
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.logger import logging


class ClubSparkPadelCrawler(ClubSparkTennisCrawler):
    """ClubSpark padel crawler.

    Reuses the tennis crawler's date-range fetch loop (one GetVenueSessions
    request per venue for the whole window) and only swaps the request category
    and the resource filter.
    """

    def __init__(self):
        super().__init__()
        self.request_strategy = ClubSparkPadelRequestStrategy()
        self.response_parser_strategy = ClubSparkPadelResponseParserStrategy()


def coroutines(
    search_dates: List[date],
) -> Coroutine[Any, Any, List[UnifiedParserSchema]]:
    """Entry point for pipeline.py."""
    crawler = ClubSparkPadelCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="padel")
    if not venues:
        logging.warning("ClubSpark: no padel venues found in DB -- skipping")

        async def _empty():
            return []

        return _empty()
    return crawler.ScraperCoroutines(venues, search_dates)


if __name__ == "__main__":
    import asyncio

    _dates = [date.today() + timedelta(days=i) for i in range(3)]
    print(f"ClubSpark padel test run for dates: {_dates}")
    crawler = ClubSparkPadelCrawler()
    venues = crawler.get_venues_by_sport_offering(sport="padel")
    if not venues:
        print(
            "[yellow]No padel venues in DB for ClubSpark. Add entries to venues.json first.[/yellow]"
        )
    else:
        results = asyncio.run(crawler._crawl_async(venues, _dates))
        print(f"Results ({len(results)} slots):")
        for r in results:
            print(r)
