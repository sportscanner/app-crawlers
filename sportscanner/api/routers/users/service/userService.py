from fastapi import HTTPException
from loguru import logger as logging
from rich import print

from sportscanner.api.routers.users.schema.user import (
    UserInCreate,
    UserInLogin,
    UserOutput,
    UserWithToken,
)
from sportscanner.core.security.authHandler import AuthHandler
from sportscanner.core.security.hashHelper import HashHelper
from sportscanner.storage.firestore.repository.UserRepository import UserRepository


class UserService:
    def __init__(self):
        self.__userRepository = UserRepository()

    def get_user_info(self, user_id: str) -> dict:
        try:
            if not self.__userRepository.user_exists_by_id(user_id=user_id):
                raise HTTPException(
                    status_code=400, detail=f"No user details found for id: {user_id}"
                )
            return self.__userRepository.get_user_by_id(user_id=user_id)
        except HTTPException as error:
            # Raise the same exception if it's already HTTPException (like user already exists case)
            raise error
        except Exception as error:
            print(error)
            raise HTTPException(
                status_code=500, detail="Failed to retrive information from Users repo"
            ) from error

    def update_user_info(self, user_id: str, updates: dict) -> None:
        self.__userRepository.update_user(user_id, updates)

    def signup(self, user_details: UserInCreate) -> UserWithToken:
        try:
            if self.__userRepository.user_exists_by_email(email=user_details.email):
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email already exists. Please login.",
                )

            hashed_password = HashHelper.get_password_hash(
                plain_password=user_details.password
            )
            user_details.password = hashed_password
            new_user: UserOutput = self.__userRepository.create_user(
                user_data=user_details
            )
            token = AuthHandler.sign_jwt(user_id=new_user.id)
            if not token:
                raise HTTPException(status_code=500, detail="Token generation failed.")
            return UserWithToken(token=token, id=new_user.id)
        except HTTPException as error:
            # Raise the same exception if it's already HTTPException (like user already exists case)
            raise error
        except Exception as error:
            logging.error(error)
            raise HTTPException(status_code=500, detail="Failed to sign up.") from error

    def login(self, login_details: UserInLogin) -> UserWithToken:
        try:
            if not self.__userRepository.user_exists_by_email(
                email=login_details.email
            ):
                raise HTTPException(
                    status_code=400,
                    detail="No account found. Please create an account.",
                )

            user = self.__userRepository.get_user_by_email(email=login_details.email)
            if not HashHelper.verify_password(
                plain_password=login_details.password, hashed_password=user.password
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid credentials. Please check your email and password.",
                )

            token = AuthHandler.sign_jwt(user_id=user.id)
            if not token:
                raise HTTPException(status_code=500, detail="Token generation failed.")
            return UserWithToken(token=token, id=user.id)
        except HTTPException as error:
            # If an HTTPException is raised, we propagate it to higher-level without modification
            raise error
        except Exception as error:
            raise HTTPException(status_code=500, detail="Failed to login.") from error


if __name__ == "__main__":
    _UserService = UserService()
    print(_UserService.get_user_info(user_id="sjsjsj"))
