import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from loguru import logger as logging

class FirebaseManager:
    def __init__(self, cred_path, project_id):
        """
        Initializes the FirebaseManager with credentials and project ID.

        Args:
            cred_path (str): Path to the Firebase service account JSON file.
            project_id (str): Your Firebase project ID.
        """
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            'projectId': project_id
        })
        self.db = firestore.client()

    def add_document(self, collection_name, document_data):
        """
        Adds a new document to a collection.

        Args:
            collection_name (str): Name of the collection.
            document_data (dict): Data to be added as a document.
        """
        doc_ref = self.db.collection(collection_name).document()
        doc_ref.set(document_data)
        logging.debug(f"Document added to collection '{collection_name}' with ID: {doc_ref.id}")

    def insert_document(self, collection_name, document_id, document_data):
        """
        Inserts a document with a specific ID into a collection.

        Args:
            collection_name (str): Name of the collection.
            document_id (str): ID of the document to be inserted.
            document_data (dict): Data to be inserted as a document.
        """
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.set(document_data)
        logging.debug(f"Document with ID '{document_id}' inserted into collection '{collection_name}'")

    def delete_document(self, collection_name, document_id):
        """
        Deletes a document from a collection.

        Args:
            collection_name (str): Name of the collection.
            document_id (str): ID of the document to be deleted.
        """
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.delete()
        logging.debug(f"Document with ID '{document_id}' deleted from collection '{collection_name}'")

    def update_document(self, collection_name, document_id, update_data):
        """
        Updates fields in an existing document.

        Args:
            collection_name (str): Name of the collection.
            document_id (str): ID of the document to be updated.
            update_data (dict): Data to be updated in the document.
        """
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc_ref.update(update_data)
        logging.debug(f"Document with ID '{document_id}' updated in collection '{collection_name}'")

    def get_document(self, collection_name, document_id):
        """
        Retrieves a document from a collection.

        Args:
            collection_name (str): Name of the collection.
            document_id (str): ID of the document to be retrieved.

        Returns:
            dict: The document data if found, otherwise None.
        """
        doc_ref = self.db.collection(collection_name).document(document_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        else:
            logging.debug(f"Document with ID '{document_id}' not found in collection '{collection_name}'")
            return None

    def get_all_documents(self, collection_name):
        """
        Retrieves all documents from a collection.

        Args:
            collection_name (str): Name of the collection.

        Returns:
            list: A list of dictionaries representing the documents.
        """
        docs = self.db.collection(collection_name).stream()
        return [doc.to_dict() for doc in docs]

# Example usage:
if __name__ == "__main__":
    # Replace with your actual credentials path and project ID
    cred_path = "sportscanner-21f2f-firebase-adminsdk-g391o-7562082fdb.json"
    project_id = "sportscanner-21f2f"

    firebase_manager = FirebaseManager(cred_path, project_id)
    # # Add a new document
    # new_document_data = {"name": "John Doe", "age": 30}
    # firebase_manager.add_document("users", new_document_data)
    #
    # # Insert a document with a specific ID
    document_data = {"name": "Jane Doe", "age": 25}
    firebase_manager.insert_document("users", "user123", document_data)

    # Delete a document
    # firebase_manager.delete_document("users", "user123")
    #
    # Update a document
    update_data = {"age": 35}
    firebase_manager.update_document("users", "user123", update_data)

    # Get a document
    document = firebase_manager.get_document("users", "user123")
    logging.debug(document)

    # Get all documents
    all_documents = firebase_manager.get_all_documents("users")
    logging.debug(all_documents)
