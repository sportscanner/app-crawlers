"""Tests for the origin-side gzip JSON response helper.

The response bytes must stay exactly what FastAPI produced before compression
was added, because the market report and venue list payloads are a public
contract.
"""

import gzip
import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.encoders import jsonable_encoder
from starlette.requests import Request
from starlette.responses import JSONResponse

from sportscanner.api.responses import json_response

PAYLOAD = {
    "sport": "padel",
    "generated_at": datetime(2026, 11, 4, 7, 30, 15, 123456),
    "history_started": date(2026, 9, 1),
    "median_price_per_hour": Decimal("12.50"),
    "label": "London · all venues",
    "venues": [{"name": f"Venue {i}", "courts": i % 7} for i in range(200)],
}


def make_request(accept_encoding: str) -> Request:
    return Request(
        {"type": "http", "headers": [(b"accept-encoding", accept_encoding.encode())]}
    )


def legacy_body(payload) -> bytes:
    """Exactly what FastAPI emitted before the helper existed."""
    return JSONResponse(jsonable_encoder(payload)).body


def test_gzipped_body_matches_the_previous_fastapi_output():
    response = json_response(PAYLOAD, make_request("gzip, deflate, br"))
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert gzip.decompress(response.body) == legacy_body(PAYLOAD)


def test_uncompressed_body_matches_the_previous_fastapi_output():
    response = json_response(PAYLOAD, make_request("identity"))
    assert "content-encoding" not in response.headers
    assert response.body == legacy_body(PAYLOAD)


def test_compression_shrinks_a_large_repetitive_payload():
    response = json_response(PAYLOAD, make_request("gzip"))
    assert len(response.body) < len(legacy_body(PAYLOAD)) / 3


def test_small_payloads_are_not_compressed():
    response = json_response({"a": 1}, make_request("gzip"))
    assert "content-encoding" not in response.headers


def test_cache_control_is_passed_through():
    response = json_response(PAYLOAD, make_request("gzip"), "public, max-age=300")
    assert response.headers["cache-control"] == "public, max-age=300"


def test_gzip_is_case_insensitive_in_accept_encoding():
    response = json_response(PAYLOAD, make_request("GZIP"))
    assert response.headers["content-encoding"] == "gzip"
