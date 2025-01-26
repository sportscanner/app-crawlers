from pydantic import BaseModel


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
