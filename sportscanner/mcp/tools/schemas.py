from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class Datasource(BaseModel):
    sourcename: str = Field(..., description="Name of the data source")
    attribution: str = Field(..., description="Attribution for the source")
    license: str = Field(..., description="License of the source")
    url: str = Field(..., description="URL for the source")

class Timezone(BaseModel):
    name: str = Field(..., description="IANA timezone name")
    offset_STD: str = Field(..., description="Standard time offset")
    offset_STD_seconds: int = Field(..., description="Standard time offset in seconds")
    offset_DST: str = Field(..., description="Daylight saving time offset")
    offset_DST_seconds: int = Field(..., description="Daylight saving time offset in seconds")
    abbreviation_STD: str = Field(..., description="Standard time abbreviation")
    abbreviation_DST: str = Field(..., description="Daylight saving time abbreviation")

class Geometry(BaseModel):
    type: str = Field(default="Point", description="Geometry type (e.g., 'Point')")
    coordinates: List[float] = Field(..., description="Longitude and latitude [lon, lat]")

class Properties(BaseModel):
    postcode: Optional[str] = Field(None, description="Postcode")
    lon: Optional[float] = Field(None, description="Longitude")
    lat: Optional[float] = Field(None, description="Latitude")
    datasource: Optional[Datasource] = Field(None, description="Data source information")
    country: Optional[str] = Field(None, description="Country name")
    country_code: Optional[str] = Field(None, description="ISO country code")
    state: Optional[str] = Field(None, description="State or province")
    county: Optional[str] = Field(None, description="County")
    district: Optional[str] = Field(None, description="District")
    iso3166_2: Optional[str] = Field(None, description="ISO 3166-2 code")
    iso3166_2_sublevel: Optional[str] = Field(None, description="Sub-level ISO code")
    city: Optional[str] = Field(None, description="City")
    state_code: Optional[str] = Field(None, description="State code")
    formatted: Optional[str] = Field(None, description="Formatted address")
    address_line1: Optional[str] = Field(None, description="First address line")
    address_line2: Optional[str] = Field(None, description="Second address line")
    timezone: Optional[Timezone] = Field(None, description="Timezone information")
    plus_code: Optional[str] = Field(None, description="Plus code")
    place_id: Optional[str] = Field(None, description="Unique place identifier")

class Feature(BaseModel):
    type: str = Field(default="Feature", description="Feature type")
    properties: Properties = Field(..., description="Feature properties")
    geometry: Geometry = Field(..., description="Geometry")

class PostcodeSearch(BaseModel):
    type: str = Field(default="FeatureCollection", description="Collection type")
    features: List[Feature] = Field(..., description="List of features")

# ------------------

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Datasource(BaseModel):
    sourcename: Optional[str] = Field(None, description="Name of the data source")
    attribution: Optional[str] = Field(None, description="Attribution for the source")
    license: Optional[str] = Field(None, description="License of the source")
    url: Optional[str] = Field(None, description="URL for the source")

class Timezone(BaseModel):
    name: Optional[str] = Field(None, description="IANA timezone name")
    offset_STD: Optional[str] = Field(None, description="Standard time offset")
    offset_STD_seconds: Optional[int] = Field(None, description="Standard time offset in seconds")
    offset_DST: Optional[str] = Field(None, description="Daylight saving time offset")
    offset_DST_seconds: Optional[int] = Field(None, description="Daylight saving time offset in seconds")
    abbreviation_STD: Optional[str] = Field(None, description="Standard time abbreviation")
    abbreviation_DST: Optional[str] = Field(None, description="Daylight saving time abbreviation")

class Rank(BaseModel):
    importance: Optional[float] = Field(None, description="Importance score")
    popularity: Optional[float] = Field(None, description="Popularity score")
    confidence: Optional[float] = Field(None, description="Overall confidence")
    confidence_city_level: Optional[float] = Field(None, description="City-level confidence")
    confidence_street_level: Optional[float] = Field(None, description="Street-level confidence")
    match_type: Optional[str] = Field(None, description="Match type")

class ParsedQuery(BaseModel):
    housenumber: Optional[str] = Field(None, description="Parsed house number")
    street: Optional[str] = Field(None, description="Parsed street")
    postcode: Optional[str] = Field(None, description="Parsed postcode")
    city: Optional[str] = Field(None, description="Parsed city")
    state: Optional[str] = Field(None, description="Parsed state")
    country: Optional[str] = Field(None, description="Parsed country")
    expected_type: Optional[str] = Field(None, description="Expected result type")

class Query(BaseModel):
    text: Optional[str] = Field(None, description="Original query text")
    parsed: Optional[ParsedQuery] = Field(None, description="Parsed components of the query")

class AddressResult(BaseModel):
    datasource: Optional[Datasource] = Field(None, description="Data source information")
    housenumber: Optional[str] = Field(None, description="House number")
    street: Optional[str] = Field(None, description="Street name")
    suburb: Optional[str] = Field(None, description="Suburb or neighborhood")
    city: Optional[str] = Field(None, description="City")
    county: Optional[str] = Field(None, description="County")
    state: Optional[str] = Field(None, description="State")
    postcode: Optional[str] = Field(None, description="Postcode")
    country: Optional[str] = Field(None, description="Country")
    country_code: Optional[str] = Field(None, description="Country code")
    lon: float = Field(..., description="Longitude (required)")
    lat: float = Field(..., description="Latitude (required)")
    formatted: Optional[str] = Field(None, description="Formatted address")
    address_line1: Optional[str] = Field(None, description="First address line")
    address_line2: Optional[str] = Field(None, description="Second address line")
    state_code: Optional[str] = Field(None, description="State code")
    result_type: Optional[str] = Field(None, description="Result type")
    rank: Optional[Rank] = Field(None, description="Ranking details")
    timezone: Optional[Timezone] = Field(None, description="Timezone information")
    place_id: Optional[str] = Field(None, description="Unique place identifier")

class ForwardGeocoding(BaseModel):
    results: List[AddressResult] = Field(..., description="List of geocoding results")
    query: Optional[Query] = Field(None, description="Query details")