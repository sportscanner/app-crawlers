from fastapi import HTTPException
from loguru import logger as logging
from rich import print

from sportscanner.api.routers.users.schema.user import (UserInCreate)
from sportscanner.storage.firestore.repository.UserRepository import UserMetadataRepository


class UserService:
    def __init__(self):
        self.userMetadataRepository = UserMetadataRepository()

    def get_user_info(self, user_id: str) -> dict:
        try:
            user_metadata = self.userMetadataRepository.get_metadata_by_userId(user_id=user_id)
            if not user_metadata:
                raise HTTPException(
                    status_code=400, detail=f"No user details found for id: {user_id}"
                )
            return self.userMetadataRepository.get_metadata_by_userId(user_id=user_id)
        except HTTPException as error:
            # Raise the same exception if it's already HTTPException (like user already exists case)
            raise error
        except Exception as error:
            print(error)
            raise HTTPException(
                status_code=500, detail="Failed to retrive information from Users repo"
            ) from error

    def create_metadata(self, user_data: UserInCreate, document_id: str):
        self.userMetadataRepository.create_metadata(user_data, document_id)

    def update_user_info(self, user_id: str, updates: dict) -> None:
        self.userMetadataRepository.update_metadata_by_userId(user_id, updates)


if __name__ == "__main__":
    _UserService = UserService()
    print(_UserService.get_user_info(user_id="sjsjsj"))