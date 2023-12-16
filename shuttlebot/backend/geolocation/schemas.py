from pydantic import BaseModel


class PostcodeMetadata(BaseModel):
    longitude: float
    latitude: float


class PostcodesResponseModel(BaseModel):
    status: int
    result: PostcodeMetadata
