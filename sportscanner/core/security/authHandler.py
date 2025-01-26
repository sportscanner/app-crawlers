import os
import time

import jwt
from loguru import logger as logging
from sqlalchemy.testing.plugin.plugin_base import logging

from sportscanner.variables import settings


class AuthHandler(object):
    @staticmethod
    def sign_jwt(user_id: str) -> str:
        """the pyjwt library expects the key exp (short for “expiration”) for proper recognition"""
        payload = {
            "user_id": user_id,
            "exp": time.time() + 15 * 24 * 60 * 60,  # 15 days in seconds
        }

        token = jwt.encode(
            payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
        )
        return token

    @staticmethod
    def decode_jwt(token: str) -> dict:
        try:
            return jwt.decode(
                token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
            )
        except jwt.ExpiredSignatureError:
            logging.error("JWT token expired, generate a new one")
            return None
        except jwt.InvalidTokenError:
            logging.error("unable to decode the token")
            return None

    @staticmethod
    def extract_token_from_bearer(bearer_token):
        """Extract the actual token from the Bearer token: `Authorization: Bearer <token>`"""
        if not bearer_token.startswith("Bearer "):
            raise ValueError("Invalid Bearer token: must start with 'Bearer '")
        return bearer_token.split(" ")[1]
