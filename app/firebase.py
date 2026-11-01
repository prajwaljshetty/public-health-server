import json
import os
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore , db

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

if service_account_json:
    try:
        service_account_info = json.loads(service_account_json)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON must contain valid service-account JSON"
        ) from error

    cred = credentials.Certificate(service_account_info)
else:
    # Local development fallback. This file is intentionally gitignored.
    service_account_path = Path(
        os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "serviceAccountKey.json")
    )
    if not service_account_path.is_absolute():
        service_account_path = PROJECT_ROOT / service_account_path

    if not service_account_path.exists():
        raise RuntimeError(
            "Firebase credentials are missing. Set FIREBASE_SERVICE_ACCOUNT_JSON "
            "in Render, or FIREBASE_SERVICE_ACCOUNT_PATH in .env."
        )

    cred = credentials.Certificate(str(service_account_path))

firebase_admin.initialize_app(
    cred,
    {
        "databaseURL": os.getenv(
            "FIREBASE_DATABASE_URL",
            "https://public-health-2026-default-rtdb.firebaseio.com/",
        )
    }
)

realtime_db = db
firestore_db = firestore.client()
