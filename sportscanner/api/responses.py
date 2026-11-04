"""JSON responses with explicit gzip compression.

Cloudflare already compresses responses for the browser, but the origin to edge
hop is uncompressed, and that is the leg the user waits on: a 450KB market
report spent about 0.35s in transit to the edge before the first byte reached
the client. The JSON here is highly repetitive, so gzip cuts it roughly tenfold.

Large responses only, and only when the caller asked for gzip, so small payloads
are not worth the CPU. Streaming endpoints (agent chat) do not use this helper.
"""

import gzip
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from starlette.requests import Request
from starlette.responses import Response

_GZIP_MIN_BYTES = 1024


def _json_default(value: Any):
    """Match what FastAPI's jsonable_encoder produces for the types we return."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def json_response(
    payload: Any,
    request: Request,
    cache_control: Optional[str] = None,
) -> Response:
    body = json.dumps(
        payload, default=_json_default, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    headers = {"Vary": "Accept-Encoding"}
    if cache_control:
        headers["Cache-Control"] = cache_control

    accepts_gzip = "gzip" in request.headers.get("accept-encoding", "").lower()
    if accepts_gzip and len(body) >= _GZIP_MIN_BYTES:
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"

    return Response(content=body, media_type="application/json", headers=headers)
