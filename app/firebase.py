import firebase_admin
from firebase_admin import credentials, firestore , db

cred = credentials.Certificate("serviceAccountKey.json")

firebase_admin.initialize_app(
    cred,
    {
        "databaseURL": "https://public-health-2026-default-rtdb.firebaseio.com/"
    }
)

realtime_db = db
firestore_db = firestore.client()