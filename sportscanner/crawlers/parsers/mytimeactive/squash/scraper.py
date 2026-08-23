from datetime import date
from typing import List

from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.mytimeactive.core.strategy import (
    GladstoneGoResponseParserStrategy,
    MytimeActiveCrawler,
    MytimeActiveRequestStrategy,
    ORGANISATION_WEBSITE,
    SQUASH_ACTIVITY_IDS,
)


class MytimeActiveSquashRequestStrategy(MytimeActiveRequestStrategy):
    def __init__(self):
        super().__init__(category="Squash", activity_ids=SQUASH_ACTIVITY_IDS)


class MytimeActiveSquashCrawler(MytimeActiveCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=MytimeActiveSquashRequestStrategy(),
            response_parser_strategy=GladstoneGoResponseParserStrategy(),
            organisation_website=ORGANISATION_WEBSITE,
        )


def coroutines(search_dates: List[date]):
    return MytimeActiveSquashCrawler().coroutines(search_dates, sport="squash", delta=6)


if __name__ == "__main__":
    from sportscanner.logger import logging

    _dates = [date.today()]
    parsed_results: List[UnifiedParserSchema] = MytimeActiveSquashCrawler().crawl(
        [], _dates
    )
    logging.success(
        f"MytimeActiveSquashCrawler finished. Got {len(parsed_results)} results."
    )
