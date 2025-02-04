import asyncio
from typing import Any, List, Tuple, Union

from sportscanner.crawlers.parsers.schema import UnifiedParserSchema


async def SportscannerCrawlerBot(
    *coroutine_lists: Union[List[Any], Any]
) -> List[UnifiedParserSchema]:
    # Normalize inputs: wrap single coroutines in a list
    normalized_inputs = [
        coro_list if isinstance(coro_list, list) else [coro_list]
        for coro_list in coroutine_lists
    ]

    # Flatten the coroutine lists and filter out invalid inputs
    coroutines = [coro for coro_list in normalized_inputs for coro in coro_list]

    # Ensure all inputs are valid coroutines
    assert all(asyncio.iscoroutine(c) for c in coroutines), "Invalid coroutine in input"

    if not coroutines:
        return []

    # Run only non-empty coroutines with asyncio.gather
    return await asyncio.gather(*coroutines)
