from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from loguru import logger as logging
from rich import print

from sportscanner.api.routers.users.schema.user import (
    UserInCreate,
    UserInLogin,
    UserOutput,
    UserWithToken,
)
from sportscanner.api.routers.users.service.userService import UserService
from sportscanner.core.security.authHandler import AuthHandler

router = APIRouter()


@router.post("/login", status_code=200, response_model=UserWithToken)
def login(loginDetails: UserInLogin):
    try:
        return UserService().login(login_details=loginDetails)
    except Exception as error:
        print(error)
        logging.error(error)
        raise error


@router.post("/signup", status_code=201, response_model=UserWithToken)
def signUp(signUpDetails: UserInCreate):
    try:
        print(signUpDetails)
        return UserService().signup(user_details=signUpDetails)
    except Exception as error:
        logging.error(error)
        raise error


@router.get("/{user_id}", status_code=200)
async def get_user_info(
    user_id: str = Path(..., title="Fetch information regarding this user id"),
    Authorization: str = Header(
        default=None, title="Bearer JWT token to authenticate user"
    ),
):
    if Authorization:
        jwt_token = AuthHandler.extract_token_from_bearer(Authorization)
        payload = AuthHandler.decode_jwt(token=jwt_token)
        print(payload)
        if payload and payload["user_id"]:
            user = UserService().get_user_info(payload["user_id"])
            return user
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authentication Credentials",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticate this endpoint using a user-specific JWT token",
        )


@router.patch("/", status_code=200)
async def update_user_info(
    request: Request,
    # user_id: str = Path(..., description="The ID of the user to update"),
    Authorization: str = Header(
        default=None, description="Bearer token to authenticate user"
    ),
):
    updates = await request.json()
    if Authorization:
        jwt_token = AuthHandler.extract_token_from_bearer(Authorization)
        payload = AuthHandler.decode_jwt(token=jwt_token)
        print(payload)
        if payload and payload["user_id"]:
            UserService().update_user_info(user_id=payload["user_id"], updates=updates)
            return {"success": True}
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authentication Credentials",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticate this endpoint using a user-specific JWT token",
        )


# router -> service -> repository -> db
# router <- service <- repository <- db
