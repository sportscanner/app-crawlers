import json
from typing import Any, Optional
from urllib.parse import quote, quote_plus

import requests
from sportscanner.logger import logging

from sportscanner.api.routers.geolocation.schemas import (
    PostcodesResponseModel,
    ResolvedLocationResponseModel,
)
from sportscanner.utils import timeit

POSTCODES_IO_BASE = "https://api.postcodes.io"


def validate_response(response):
    if response.status_code == 200:
        response_dict = json.loads(response.text)
        logging.debug(f"API Response:\n{response_dict}\n")
        return response_dict
    else:
        logging.error(f"Request failed with status code {response.status_code}")
        return None


def _get_json(url: str) -> Optional[dict[str, Any]]:
    headers, payload = {}, {}
    try:
        response = requests.request("GET", url, headers=headers, data=payload, timeout=10)
    except requests.RequestException as exc:
        logging.error(f"Request failed for {url}: {type(exc).__name__}: {exc}")
        return None
    return validate_response(response)


@timeit
def get_postcode_metadata(postcode: str) -> Optional[PostcodesResponseModel]:
    url = f"{POSTCODES_IO_BASE}/postcodes/{quote(postcode, safe='')}"
    logging.info(f"Requests URL: {url}")

    validated_response = _get_json(url)
    return (
        PostcodesResponseModel(**validated_response)
        if validated_response is not None
        else None
    )


def postcode_autocompletion(search_term: str, limit: int = 5):
    url = f"{POSTCODES_IO_BASE}/postcodes/{quote(search_term, safe='')}/autocomplete"
    validated_response = _get_json(url)
    if validated_response is None:
        return []
    return (
        validated_response["result"][:limit]
        if validated_response.get("result") is not None
        else []
    )


@timeit
def validate_uk_postcode(postcode: str) -> bool:
    url = f"{POSTCODES_IO_BASE}/postcodes/{quote(postcode, safe='')}/validate"
    logging.info(f"Requests URL: {url}")

    validated_response = _get_json(url)
    if validated_response is None:
        return False
    return True if validated_response.get("result", "") is True else False


def get_nearest_postcode_from_coordinates(
    latitude: float,
    longitude: float,
) -> Optional[str]:
    url = (
        f"{POSTCODES_IO_BASE}/postcodes?"
        f"lon={longitude}&lat={latitude}&limit=1"
    )
    validated_response = _get_json(url)
    if validated_response is None:
        return None

    results = validated_response.get("result") or []
    if not results:
        return None
    return results[0].get("postcode")


def get_outcode_metadata(outcode: str) -> Optional[dict[str, Any]]:
    url = f"{POSTCODES_IO_BASE}/outcodes/{quote(outcode, safe='')}"
    validated_response = _get_json(url)
    if validated_response is None:
        return None
    return validated_response.get("result")


def search_places(query: str, limit: int = 5) -> list[dict[str, Any]]:
    url = f"{POSTCODES_IO_BASE}/places?q={quote_plus(query)}&limit={limit}"
    validated_response = _get_json(url)
    if validated_response is None:
        return []

    results = validated_response.get("result")
    return results[:limit] if isinstance(results, list) else []


def resolve_location_query(query: str) -> ResolvedLocationResponseModel:
    """
    Resolve flexible UK location input into a full postcode + coordinates.

    Supported input examples:
    - full postcode: `SW1A 1AA`
    - outcode / district: `E14`
    - place name: `Paddington`
    """
    cleaned_query = " ".join(query.strip().split())
    if not cleaned_query:
        return ResolvedLocationResponseModel(
            query=query,
            source="unresolved",
            message="Please provide a postcode, district, or London place name.",
        )

    # 1) Exact full-postcode match.
    if validate_uk_postcode(cleaned_query):
        metadata = get_postcode_metadata(cleaned_query)
        if metadata is not None:
            return ResolvedLocationResponseModel(
                query=cleaned_query,
                resolved_postcode=metadata.result.postcode,
                source="postcode_exact",
                latitude=metadata.result.latitude,
                longitude=metadata.result.longitude,
            )
        return ResolvedLocationResponseModel(
            query=cleaned_query,
            resolved_postcode=cleaned_query.upper(),
            source="postcode_exact",
        )

    # 2) Postcode fragment / autocomplete (for partial postcodes like E14, SW1A).
    postcode_suggestions = postcode_autocompletion(cleaned_query, limit=5)
    if postcode_suggestions:
        best_postcode = postcode_suggestions[0]
        metadata = get_postcode_metadata(best_postcode)
        return ResolvedLocationResponseModel(
            query=cleaned_query,
            resolved_postcode=best_postcode,
            source="postcode_autocomplete",
            latitude=metadata.result.latitude if metadata is not None else None,
            longitude=metadata.result.longitude if metadata is not None else None,
            suggestions=postcode_suggestions,
        )

    # 3) Outcode centroid fallback.
    outcode_metadata = get_outcode_metadata(cleaned_query.upper())
    if outcode_metadata:
        latitude = outcode_metadata.get("latitude")
        longitude = outcode_metadata.get("longitude")
        resolved_postcode = None
        if latitude is not None and longitude is not None:
            resolved_postcode = get_nearest_postcode_from_coordinates(
                latitude=latitude,
                longitude=longitude,
            )
        return ResolvedLocationResponseModel(
            query=cleaned_query,
            resolved_postcode=resolved_postcode,
            source="outcode_centroid",
            display_name=f"Outcode {cleaned_query.upper()} centroid",
            latitude=latitude,
            longitude=longitude,
            suggestions=[cleaned_query.upper()],
        )

    # 4) Place-name search fallback (for queries like Paddington, Canary Wharf).
    place_candidates = search_places(cleaned_query, limit=5)
    if place_candidates:
        london_candidates = [
            candidate
            for candidate in place_candidates
            if (
                str(candidate.get("region") or "").lower() == "london"
                or str(candidate.get("county_unitary") or "").lower()
                == "greater london"
            )
        ]
        best_match = london_candidates[0] if london_candidates else place_candidates[0]
        latitude = best_match.get("latitude")
        longitude = best_match.get("longitude")
        resolved_postcode = None
        if latitude is not None and longitude is not None:
            resolved_postcode = get_nearest_postcode_from_coordinates(
                latitude=latitude,
                longitude=longitude,
            )

        def _place_label(place: dict[str, Any]) -> str:
            name = place.get("name_1") or place.get("name") or "Unknown place"
            region = place.get("region")
            if region:
                return f"{name}, {region}"
            return str(name)

        place_names = [
            _place_label(candidate)
            for candidate in place_candidates
        ]

        return ResolvedLocationResponseModel(
            query=cleaned_query,
            resolved_postcode=resolved_postcode,
            source="place_search",
            display_name=_place_label(best_match),
            latitude=latitude,
            longitude=longitude,
            suggestions=place_names,
        )

    return ResolvedLocationResponseModel(
        query=cleaned_query,
        source="unresolved",
        message=(
            "Could not resolve that location. Try a fuller postcode (for example "
            "`E14 5AB`) or a well-known London place name."
        ),
    )


if __name__ == "__main__":
    logging.info(
        "Running script standalone with testdata for London bridge postcode: SE1 9BG"
    )
    logging.info(validate_uk_postcode("SE1 9BG"))
    logging.success(get_postcode_metadata("SE1 9BG"))
    logging.success(get_postcode_metadata("SE29qq"))
