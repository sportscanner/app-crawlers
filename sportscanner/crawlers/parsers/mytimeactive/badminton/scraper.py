from datetime import date
from typing import List

from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.mytimeactive.core.strategy import (
    BADMINTON_ACTIVITY_IDS,
    GladstoneGoResponseParserStrategy,
    MytimeActiveCrawler,
    MytimeActiveRequestStrategy,
    ORGANISATION_WEBSITE,
)


class MytimeActiveBadmintonRequestStrategy(MytimeActiveRequestStrategy):
    def __init__(self):
        super().__init__(category="Badminton", activity_ids=BADMINTON_ACTIVITY_IDS)


class MytimeActiveBadmintonCrawler(MytimeActiveCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=MytimeActiveBadmintonRequestStrategy(),
            response_parser_strategy=GladstoneGoResponseParserStrategy(),
            organisation_website=ORGANISATION_WEBSITE,
        )


def coroutines(search_dates: List[date]):
    return MytimeActiveBadmintonCrawler().coroutines(
        search_dates, sport="badminton", delta=6
    )


if __name__ == "__main__":
    from sportscanner.logger import logging

    _dates = [date.today()]
    parsed_results: List[UnifiedParserSchema] = MytimeActiveBadmintonCrawler().crawl(
        [], _dates
    )
    logging.success(
        f"MytimeActiveBadmintonCrawler finished. Got {len(parsed_results)} results."
    )
