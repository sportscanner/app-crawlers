from pydantic import BaseModel


class PostcodeMetadata(BaseModel):
    longitude: float = -0.128294
    latitude: float = 51.507209


class PostcodesResponseModel(BaseModel):
    status: int
    result: PostcodeMetadata
