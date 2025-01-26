from firebase_admin import credentials, firestore, get_app, initialize_app
from firebase_admin.exceptions import FirebaseError
from loguru import logger as logging

from sportscanner.variables import settings


class FirebaseManager:
    def __init__(self):
        """
        Initializes the FirebaseManager with credentials and project ID.
        Ensures Firebase is only initialized once to avoid errors.
        """
        try:
            # Check if the default app is already initialized
            get_app()
        except ValueError:
            # Initialize Firebase only if it hasn't been initialized yet
            cred = credentials.Certificate(settings.CLOUD_FIRESTORE_CREDENTIALS_PATH)
            initialize_app(cred, {"projectId": settings.CLOUD_FIRESTORE_PROJECT_ID})

        # Firestore client setup
        self.db = firestore.client()
        self.user_collection = self.db.collection(settings.FIRESTORE_USER_COLLECTION)
