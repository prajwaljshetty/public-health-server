from fastapi import APIRouter

# Model :
from app.models.worker import WorkerCreate, WorkerRegister , WorkerLogin

# Firebase :
from app.firebase import firestore_db

# Filter :
from google.cloud.firestore_v1 import transactional
from google.cloud.firestore_v1.base_query import FieldFilter

# HTTP :
from fastapi import Depends , HTTPException, status

# Unique :
import uuid

# Token Creation and Validations :
from app.auth import (
    create_access_token ,
    create_refresh_token ,
    get_current_user , 
    get_refresh_token
)

# Password Hasher :
from app.hasher import (
    hash_password ,
    verify_password ,
)

router = APIRouter()


def _highest_existing_worker_number() -> int:
    """Return the highest numeric PW worker ID already stored in Firestore."""
    highest = 100

    for document in firestore_db.collection("workers").stream():
        worker_id = (document.to_dict() or {}).get("worker_id", "")
        if not isinstance(worker_id, str) or not worker_id.startswith("PW-"):
            continue

        try:
            highest = max(highest, int(worker_id.removeprefix("PW-")))
        except ValueError:
            continue

    return highest


def _generate_worker_id() -> str:
    """Allocate a unique sequential worker ID starting at PW-101."""
    counter_ref = firestore_db.collection("metadata").document("worker_counter")
    first_available = _highest_existing_worker_number() + 1
    transaction = firestore_db.transaction()

    @transactional
    def allocate(transaction):
        counter = transaction.get(counter_ref)
        counter_data = counter.to_dict() if counter.exists else {}
        next_number = max(
            first_available,
            int(counter_data.get("next_number", 101)),
        )

        transaction.set(
            counter_ref,
            {"next_number": next_number + 1},
            merge=True,
        )
        return f"PW-{next_number}"

    return allocate(transaction)


@router.post("/add", status_code=status.HTTP_201_CREATED)
def add_worker(worker: WorkerCreate):
    """Create an administrator-provisioned worker with an automatic PW ID."""
    name = worker.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Worker name cannot be empty",
        )

    worker_id = _generate_worker_id()
    user_id = str(uuid.uuid4())

    firestore_db.collection("workers").document(user_id).set({
        "user_id": user_id,
        "worker_id": worker_id,
        "user_name": name,
        "password": hash_password(worker.password),
        "role": "worker",
    })

    return {
        "status": True,
        "message": "Worker added successfully",
        "worker": {
            "user_id": user_id,
            "worker_id": worker_id,
            "name": name,
        },
    }

@router.post("/createaccount")
def create_account(worker: WorkerRegister):

    # Check whether worker already exists
    users = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker.worker_id
        )
    ).limit(1).stream()

    if next(users, None):
        return {
            "status": False,
            "message": "WORKER_ALREADY_EXISTS",
            "user_id": None
        }

    # Generate user ID
    user_id = str(uuid.uuid4())

    # Hash password
    password = hash_password(worker.password)

    # Save worker
    firestore_db.collection("workers").document(user_id).set({
        "user_id": user_id,
        "worker_id": worker.worker_id,
        "user_name": worker.user_name,
        "phoneno": worker.phoneno,
        "password": password,
        "role": "worker"
    })

    # Generate Access Token
    access_token = create_access_token(user_id=user_id)

    # Generate Refresh Token
    refresh_token = create_refresh_token(user_id=user_id)

    # Return response
    return {
        "status": True,
        "message": "Account created successfully",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@router.post("/login")
def login(user: WorkerLogin):
    
    # Find worker by worker ID
    users = firestore_db.collection("workers").where(
        filter=FieldFilter("worker_id", "==", user.worker_id)
    ).limit(1).stream()


    existing_user = next(users, None)

    # User does not exist
    if existing_user is None:
        return {
            "status": False,
            "message": "USER_NOT_FOUND",
            "user_id": None
        }

    user_data = existing_user.to_dict()

    print(user.password)

    # Check password with Hashed Password
    if not verify_password(hashed_password = user_data["password"] , password = user.password):
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "user_id": None
        }

    user_id = user_data['user_id']

    # Generate tokens
    access_token = create_access_token(user_id=user_id)
    refresh_token = create_refresh_token(user_id=user_id)

    print(access_token,refresh_token)

    return {
        "status": True,
        "message": "Login successful",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):
    # Get user ID from JWT payload
    user_id = payload["sub"]

    print(user_id)

    # Fetch worker document
    user = firestore_db.collection("workers").document(user_id).get()

    # Check whether the worker exists
    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "user_data": None
        }

    # Extract worker data
    user_data = user.to_dict()

    return {
        "status": True,
        "message": "User data fetched successfully",
        "user_data": {
            "user_id": user_data["user_id"],
            "role": user_data["role"],
            "user_name": user_data["user_name"],
            "phoneno": user_data.get("phoneno", "")
        }
    }

@router.post("/refresh")
def get_access_token(
    request_data: dict = Depends(get_refresh_token)
):
    # Get user ID
    user_id = request_data["sub"]

    # Check whether the household exists
    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NO_LONGER_EXIST",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate a new access token
    access_token = create_access_token(user_id=user_id)

    return {
        "status": True,
        "message": "Access token refreshed successfully",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 900
    }
