from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger as logging
from rich import print

from sportscanner.storage.firestore.models.user import User, UserInCreate, UserInCreateConfirmation
from sportscanner.storage.firestore.repository.Base import FirebaseManager
from sportscanner.variables import settings


class UserMetadataRepository(FirebaseManager):
    def create_metadata(self, user_data: UserInCreate, document_id: str) -> bool:
        doc_ref = self.user_collection.document(document_id)  # Use the provided ID
        user_data_dict = user_data.model_dump()
        user_data_dict["created_at"] = datetime.utcnow().isoformat()
        doc_ref.set(user_data_dict)
        logging.info(
            f"Document added to collection '{settings.FIRESTORE_USER_COLLECTION}' with ID: {doc_ref.id}"
        )
        return True

    def get_metadata_by_userId(self, user_id: str) -> Optional[dict]:
        user_doc = self.user_collection.document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return user_data
        else:
            return None

    def get_all_users_metadata(self) -> List[dict]:
        docs = self.user_collection.stream()
        return [doc.to_dict() for doc in docs]

    def update_metadata_by_userId(self, user_id: str, updates: dict):
        """
        Updates an existing user document.

        Args:
          user_id: The ID of the user document.
          updates: A dictionary containing the fields to update.
                   Example: {'age': 31}
        """
        user_ref = self.user_collection.document(user_id)
        user_ref.update(updates)

    def delete_metadata_by_userId(self, user_id: str) -> None:
        doc_ref = self.user_collection.document(user_id)
        doc_ref.delete()
        logging.warning(f"User with id: {user_id} deleted")


    def check_metadata_exists_by_userId(self, user_id: str) -> bool:
        """Checks if user exists based on UID"""
        user_doc = self.user_collection.document(user_id).get()
        if user_doc.exists:
            return True
        else:
            return False


if __name__ == "__main__":
    userService = UserMetadataRepository()
    print(
        userService.get_metadata_by_userId("kp_e27bc96e0fd849c4baf3e7ed7ac3f322")
    )
