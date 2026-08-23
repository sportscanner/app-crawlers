from datetime import date
from typing import List

from sportscanner.crawlers.parsers.better.core.strategy import (
    BetterLeisureResponseParserStrategy,
    BetterStyleCrawler,
)
from sportscanner.crawlers.parsers.core.schemas import UnifiedParserSchema
from sportscanner.crawlers.parsers.visionrcl.core.strategy import (
    VisionRclRequestStrategy,
)


class VisionRclBadmintonRequestStrategy(VisionRclRequestStrategy):
    activity_slugs = ["badminton/v2"]
    category = "Badminton"


class VisionRclBadmintonCrawler(BetterStyleCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=VisionRclBadmintonRequestStrategy(),
            response_parser_strategy=BetterLeisureResponseParserStrategy(),
            organisation_website="https://www.visionrcl.org.uk",
        )


def coroutines(search_dates: List[date]):
    return VisionRclBadmintonCrawler().coroutines(
        search_dates, sport="badminton", delta=6
    )


if __name__ == "__main__":
    from sportscanner.logger import logging

    _dates = [date.today()]
    parsed_results: List[UnifiedParserSchema] = VisionRclBadmintonCrawler().crawl(
        [], _dates
    )
    logging.success(
        f"VisionRclBadmintonCrawler finished. Got {len(parsed_results)} results."
    )
