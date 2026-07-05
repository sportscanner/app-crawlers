from pydantic import ValidationError
from sqlalchemy import text

from sportscanner.crawlers.parsers.core.schemas import RawResponseData, RequestDetailsWithMetadata
from sportscanner.crawlers.parsers.core.interfaces import AbstractResponseParserStrategy, BaseCrawler
from datetime import date, datetime
from typing import Any, List
from sportscanner.crawlers.helpers import override

from sportscanner.logger import logging
from rich import print

import sportscanner.storage.postgres.database as db
from sportscanner.crawlers.parsers.better.core.schema import BetterApiResponseSchema
from sportscanner.crawlers.parsers.core.schemas import (UnifiedParserSchema)


# Slot categories map 1:1 to their master tables. Allow-listed because a table
# name can't be a bound SQL parameter — this keeps it off the f-string injection
# path even though `category` is internally controlled today.
_CATEGORY_TO_TABLE = {
    "badminton": "badminton",
    "squash": "squash",
    "pickleball": "pickleball",
    "padel": "padel",
}


def populate_blank_response_for_upserts(
        category: str, composite_key: str, search_date: date
) -> List[UnifiedParserSchema]:
    """Re-emit a venue/date's existing DB rows as zeroed-out (spaces=0) slots.

    Better/GLL returns a 200 with no `data` when a previously-listed activity is
    withdrawn. Rather than leaving stale availability in the master table, we
    reload those same slots with spaces=0 so the upsert marks them unavailable.
    """
    table_name = _CATEGORY_TO_TABLE.get(category.lower())
    if table_name is None:
        logging.error(f"No master table mapped for category '{category}'; skipping blanks")
        return []
    clause = text(
        f"SELECT * FROM {table_name} t1 "
        f"WHERE t1.composite_key = :composite_key AND t1.date = :search_date"
    ).bindparams(composite_key=composite_key, search_date=search_date)
    rows = db.get_all_rows(db.engine, None, clause)
    return [
        UnifiedParserSchema(
            category=row.category,
            starting_time=row.starting_time,
            ending_time=row.ending_time,
            date=row.date,
            price=row.price,
            spaces=0,
            composite_key=row.composite_key,
            last_refreshed=datetime.now(),
            booking_url=None,
        )
        for row in rows
    ]


class BetterLeisureResponseParserStrategy(AbstractResponseParserStrategy):
    def _transform_raw_response_to_typed(self, api_response) -> List[BetterApiResponseSchema]:
        aligned_api_response = []
        if isinstance(api_response, dict):
            try:
                aligned_api_response.extend(
                    [
                        BetterApiResponseSchema(**response_block)
                        for _key, response_block in api_response.items()
                    ]
                )
            except ValidationError as e:
                logging.error(
                    f"Unable to apply Better API response schema to raw API json:\n{e}"
                )
                logging.error(f"{api_response}")
        else:
            if len(api_response) > 0:
                try:
                    aligned_api_response.extend(
                        [
                            BetterApiResponseSchema(**response_block)
                            for response_block in api_response
                        ]
                    )
                except ValidationError as e:
                    logging.error(
                        f"Unable to apply BetterApiResponseSchema to raw API json:\n{e}"
                    )
        logging.debug(f"Data aligned with overall schema: {BetterApiResponseSchema}")
        return aligned_api_response

    @override
    def parse(self, raw_response: RawResponseData) -> List[UnifiedParserSchema]:
        raw_response_typed: List[BetterApiResponseSchema] = self._transform_raw_response_to_typed(raw_response.content)
        unified_schema_output = []
        for slot in raw_response_typed:
            try:
                unified_schema_output.append(
                    UnifiedParserSchema(
                        category=raw_response.requestMetadata.metadata.category,
                        starting_time=datetime.strptime(
                            slot.starts_at.format_24_hour, "%H:%M"
                        ).time(),
                        ending_time=datetime.strptime(
                            slot.ends_at.format_24_hour, "%H:%M"
                        ).time(),
                        date=raw_response.requestMetadata.metadata.date,
                        price=slot.price.formatted_amount,
                        spaces=slot.spaces,
                        composite_key=raw_response.requestMetadata.metadata.sportsCentre.composite_key,
                        last_refreshed=raw_response.requestMetadata.metadata.last_refreshed,
                        booking_url=raw_response.requestMetadata.metadata.booking_url
                    )
                )
            except ValueError as e:
                print(f"Error parsing time for slot {slot.starts_at.format_24_hour}: {e}")
        return unified_schema_output


class BetterStyleCrawler(BaseCrawler):
    """BaseCrawler variant for the Better/GLL-style times API (also used by the
    flow.onl instances — ActiveLambeth, Haringey).

    These APIs wrap the slot list under a top-level `data` key, and a 200 with an
    empty/absent `data` means "this activity has no live listing" — which we treat
    as a signal to zero-out any existing DB rows rather than as "no slots found".
    """

    @override
    def _extract_content(self, validated_response: Any) -> Any:
        return validated_response.get("data") if isinstance(validated_response, dict) else None

    @override
    def _on_empty_response(self, request_details: RequestDetailsWithMetadata) -> List[UnifiedParserSchema]:
        logging.debug(
            f"No 'data' field in API response for {request_details.url} - populating blanks for upserts"
        )
        return populate_blank_response_for_upserts(
            category=request_details.metadata.category,
            composite_key=request_details.metadata.sportsCentre.composite_key,
            search_date=request_details.metadata.date,
        )
