from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PostcodeMetadata(BaseModel):
    postcode: str
    region: str
    longitude: float
    latitude: float
    northings: int
    eastings: int


class PostcodesResponseModel(BaseModel):
    status: int
    result: PostcodeMetadata


class ResolvedLocationResponseModel(BaseModel):
    query: str = Field(..., description="Raw location text submitted by the user.")
    resolved_postcode: Optional[str] = Field(
        default=None,
        description=(
            "Resolved full UK postcode suitable for SportScanner proximity "
            "searches, when available."
        ),
    )
    source: Literal[
        "postcode_exact",
        "postcode_autocomplete",
        "outcode_centroid",
        "place_search",
        "unresolved",
    ] = Field(
        ...,
        description="Resolution strategy used for this query.",
    )
    display_name: Optional[str] = Field(
        default=None,
        description="Human-readable place label when resolved via place search.",
    )
    latitude: Optional[float] = Field(
        default=None,
        description="Resolved latitude when available.",
    )
    longitude: Optional[float] = Field(
        default=None,
        description="Resolved longitude when available.",
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description=(
            "Alternative candidates (for example postcode completions or place "
            "name matches)."
        ),
    )
    message: Optional[str] = Field(
        default=None,
        description="Optional resolution hint when query could not be resolved.",
    )
