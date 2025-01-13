from firebase_admin import credentials, firestore, initialize_app
from pydantic import BaseModel
from typing import Optional
from rich import print
# Initialize Firestore
cred = credentials.Certificate("sportscanner-21f2f-firebase-adminsdk-g391o-8982b01a20.json")
app = initialize_app(cred)
db = firestore.client()

# User Data Model
class User(BaseModel):
    uid: str
    email: str
    password: str

# Signup Function
def signup(email, password):
    # Reference to the 'users' collection
    users_collection = db.collection('users')
    try:
        # Check if user already exists (by email)
        docs = users_collection.where('email', '==', email).stream()
        if len(list(docs)) > 0:
            return {"status": "error", "message": "User with this email already exists."}

        # Create a new user document
        user = User(uid=users_collection.document().id, email=email, password=password)
        doc_ref = users_collection.document(user.uid)
        doc_ref.set({
            'uid': user.uid,
            'email': user.email,
            'password': user.password
        })
        return {"status": "success", "message": "User created successfully."}
    except Exception as e:
        print(f"Error during signup: {e}")
        return {"status": "error", "message": "An error occurred during signup."}

# Signin Function
def signin(email, password):
    # Reference to the 'users' collection
    users_collection = db.collection('users')
    try:
        docs = users_collection.where('email', '==', email).stream()
        user_data = list(docs)

        if len(user_data) == 0:
            return {"status": "error", "message": "User not found."}

        user = user_data[0].to_dict()
        if user['password'] != password:
            return {"status": "error", "message": "Incorrect password."}

        return {"status": "success", "message": "Signin successful.", "user": user}
    except Exception as e:
        print(f"Error during signin: {e}")
        return {"status": "error", "message": "An error occurred during signin."}

# Example Usage
print(signup("user1@example.com", "john_doe"))
print(signin("user@example.com", "secret123"))