from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger as logging
from rich import print

from sportscanner.storage.firestore.models.user import User, UserInCreate, UserOutput
from sportscanner.storage.firestore.repository.Base import FirebaseManager
from sportscanner.variables import settings


class UserRepository(FirebaseManager):
    def create_user(self, user_data: UserInCreate) -> UserOutput:
        doc_ref = self.user_collection.document()
        # Add a timestamp to the user_data
        user_data_dict = user_data.model_dump()  # Convert the model to a dictionary
        user_data_dict["created_at"] = (
            datetime.utcnow().isoformat()
        )  # Add a UTC timestamp
        doc_ref.set(user_data_dict)
        logging.info(
            f"Document added to collection '{settings.FIRESTORE_USER_COLLECTION}' with ID: {doc_ref.id}"
        )
        return UserOutput(
            id=doc_ref.id, fullName=user_data.fullName, email=user_data.email
        )

    def get_user_by_email(self, email: str) -> Optional[User]:
        user_docs = self.user_collection.where(
            field_path="email", op_string="==", value=email
        ).get()
        if len(user_docs) > 0:
            user_doc = user_docs[0]  # Assuming you only expect one document for email
            user_data = user_doc.to_dict()
            user_data["id"] = user_doc.id
            return User(**user_data)
        else:
            return None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        user_doc = self.user_collection.document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_data["id"] = user_doc.id  # Add the document ID to the dictionary
            # Remove the 'password' key if it exists
            user_data.pop("password", None)
            return user_data
        else:
            return None

    def get_all_users(self) -> List[User]:
        docs = self.user_collection.stream()
        return [User(**doc.to_dict()) for doc in docs]

    def update_user(self, user_id: str, updates: dict):
        """
        Updates an existing user document.

        Args:
          user_id: The ID of the user document.
          updates: A dictionary containing the fields to update.
                   Example: {'age': 31}
        """
        user_ref = self.user_collection.document(user_id)
        user_ref.update(updates)

    def delete_user_by_id(self, user_id: str) -> None:
        doc_ref = self.user_collection.document(user_id)
        doc_ref.delete()
        logging.warning(f"User with id: {user_id} deleted")

    def user_exists_by_email(self, email: str) -> bool:
        """Checks if user exists based on Email address"""
        user_docs = self.user_collection.where(
            field_path="email", op_string="==", value=email
        ).get()
        return True if len(user_docs) > 0 else False

    def user_exists_by_id(self, user_id: str) -> bool:
        """Checks if user exists based on UID"""
        user_doc = self.user_collection.document(user_id).get()
        if user_doc.exists:
            return True
        else:
            return False


if __name__ == "__main__":
    userService = UserRepository()
    print(
        userService.update_user(
            user_id="47fmVcsaUrQJbUFvbTEP",
            updates={"preferredVenues": ["Layman centre", "Talacre"]},
        )
    )
