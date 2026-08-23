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


class VisionRclSquashRequestStrategy(VisionRclRequestStrategy):
    activity_slugs = ["squash-60/v2", "squash-45/v2"]
    category = "Squash"


class VisionRclSquashCrawler(BetterStyleCrawler):
    def __init__(self):
        super().__init__(
            request_strategy=VisionRclSquashRequestStrategy(),
            response_parser_strategy=BetterLeisureResponseParserStrategy(),
            organisation_website="https://www.visionrcl.org.uk",
        )


def coroutines(search_dates: List[date]):
    return VisionRclSquashCrawler().coroutines(search_dates, sport="squash", delta=6)


if __name__ == "__main__":
    from sportscanner.logger import logging

    _dates = [date.today()]
    parsed_results: List[UnifiedParserSchema] = VisionRclSquashCrawler().crawl(
        [], _dates
    )
    logging.success(
        f"VisionRclSquashCrawler finished. Got {len(parsed_results)} results."
    )
