from fastapi import APIRouter , WebSocket , WebSocketDisconnect

# Firebase :
from firebase_admin import db
from app.firebase import firestore_db , realtime_db


# Asychronus :
import asyncio

# HTTP :
from fastapi import Depends , HTTPException, status

# Token Creation and Validations :
from app.auth import (
    create_access_token ,
    create_refresh_token ,
    validate_token ,
    get_current_user , 
    get_refresh_token
)

# Password Hasher :
from app.hasher import (
    hash_password , 
    verify_password
)

# Unique :
import uuid

# User Model :
from app.models.household import HousholdCreate , HouseholdLogin , HouseholdRequestData

# Filter :
from google.cloud.firestore_v1.base_query import FieldFilter

router = APIRouter()

# Post :
@router.post("/create")
def create(user: HousholdCreate):
    # Check whether user already exists
    users = firestore_db.collection("households").where(
            filter=FieldFilter(
                "phoneno",
                "==",
                user.phoneno
    )).stream()

    # User does exist
    if next(users, None):
        return {
            "status": False,
            "message": "PHONE_NUMBER_ALREADY_REGISTERED",
            "user_id": None
        }

    # Generate uid
    user_id = str(uuid.uuid4())

    # Hash password
    password = hash_password(user.password)

    # Save household
    firestore_db.collection("households").document(user_id).set({
        "user_id": user_id,
        "user_name": user.username,
        "phoneno": user.phoneno,
        "password": password
    })

    # Generate Access Token
    access_token = create_access_token(user_id= user_id)

    # Generate Refresh Token
    refresh_token = create_refresh_token(user_id= user_id)

    # Return response
    return {
        "status": True,
        "message": "Account created successfully",
        "user_id": user_id,
        "access_token" : access_token ,
        "refresh_token" : refresh_token
    }

@router.post("/login")
def login(user: HouseholdLogin):
    # Check whether user exists
    users = firestore_db.collection("households").where(
        filter=FieldFilter(
            "phoneno",
            "==",
            user.phoneno
        )
    ).limit(1).stream()

    existing_user = next(users, None)

    # User does not exist
    if existing_user is None:
        return {
            "status": False,
            "message": "USER_NOT_FOUND",
            "user_id": None
        }

    # Get user data
    user_data = existing_user.to_dict()

    # Extract user password
    user_id = user_data["user_id"]

    # Check password with Hashed Password
    if not verify_password(hashed_password = user_id , password = user.password):
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "user_id": None
        }

    # Generate Refresh Token
    refresh_token = create_refresh_token(user_id= user_id)
    
    # Generate Access Token
    access_token = create_access_token(user_id= user_id)

    # Return response
    return {
        "status": True,
        "message": "Login successful",
        "user_id": user_id,
        "access_token" : access_token ,
        "refresh_token" : refresh_token
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):

    # Get user ID
    user_id = payload["sub"]

    # Check user exists
    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "user_data": None
        }

    # Get user data from Firestore
    user_data = user.to_dict()

    # Check whether the user already has an active pickup request
    pickups = realtime_db.reference("pickups/requests").get()

    pickup_id = None
    current_status = "idle"

    if pickups:
        for key, pickup in pickups.items():
            if pickup.get("user_id") == user_id:
                pickup_id = key
                break

    if pickup_id:
        pickup_status = realtime_db.reference(
            f"pickups/status/{pickup_id}"
        ).get()

        if pickup_status:
            current_status = pickup_status.get("status", "idle")

    # Return household data
    return {
        "status": True,
        "message": "User data fetched successfully",
        "user_data": {
            "user_id": user_id,
            "role": "household",
            "user_name": user_data["user_name"],
            "phoneno": user_data["phoneno"],
            "pickup_status" : current_status
        }
    }

@router.post("/pickup/request")
async def request_pickup(
    household_request_data: HouseholdRequestData,
    payload: dict = Depends(get_current_user),
):
    # Get authenticated household ID from the JWT
    user_id = payload["sub"]

    # Verify household exists
    user = (
        firestore_db.collection("households")
        .document(user_id)
        .get()
    )

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND",
        )

    # Generate pickup ID
    pickup_id = str(uuid.uuid4())

    # Normalize timestamp
    pickup_time = household_request_data.time.isoformat()

    # Save pickup request
    realtime_db.reference(
        "pickups/requests"
    ).child(pickup_id).set({
        "pickupid": pickup_id,
        "user_id": user_id,
        "time": pickup_time,
        "coordinate": {
            "latitude": household_request_data.coordinate.latitude,
            "longitude": household_request_data.coordinate.longitude,
        },
        "qna": household_request_data.qna,
        "status": "requested",
    })

    #Update pickup status 
    realtime_db.reference(
        "pickups/status"
    ).child(pickup_id).set({
        "user_id": user_id ,
        "status" : "requested"
    })

    return {
        "status": True,
        "message": "Pickup requested successfully",
        "pickupid": pickup_id,
    }

@router.get("/pickup/data")
def get_pickup_data(payload: dict = Depends(get_current_user)):
    # Get user ID
    user_id = payload["sub"]

    # Check whether user exists
    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "pickupdata": None
        }

    # Fetch pickup data
    pickups = (
        realtime_db.reference("pickups/requests")
        .order_by_child("user_id")
        .equal_to(user_id)
        .get()
    )

    # Pickup data does not exist
    if not pickups:
        return {
            "status": True,
            "message": "No pickup request found",
            "pickup_data": None
        }

    pickupdata = next(iter(pickups.values()))

    # Return pickup details
    return {
        "status": True,
        "message": "Pickup data fetched successfully",
        "pickup_data": pickupdata
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

@router.websocket("/pickup/status/{pickup_id}")
async def pickup_status_stream(
    websocket: WebSocket,
    pickup_id: str,
):
    await websocket.accept()

    user_id = None
    listener = None

    try:
        token = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=10,
        )

        payload = validate_token(token, "access")

        if not payload:
            await websocket.close(
                code=1008,
                reason="Invalid access token",
            )
            return

        user_id = payload["sub"]

        pickup_status_db = db.reference(
            f"pickups/status/{pickup_id}"
        )

        pickup_owner_db = db.reference(
            f"pickups/requests/{pickup_id}/user_id"
        )

        initial_data = pickup_status_db.get()
        owner_id = pickup_owner_db.get()

        if owner_id != user_id:
            await websocket.send_json({
                "status": False,
                "message": "Unauthorized",
                "pickup_data": {},
            })
            await websocket.close(
                code=1008,
                reason="Unauthorized",
            )
            return

        if isinstance(initial_data, dict):
            initial_status = initial_data.get("status")
        elif isinstance(initial_data, str):
            initial_status = initial_data
        else:
            await websocket.send_json({
                "status": False,
                "message": "Pickup not found",
                "pickup_data": {},
            })
            await websocket.close(
                code=1008,
                reason="Pickup not found",
            )
            return

        if not isinstance(initial_status, str):
            await websocket.close(
                code=1008,
                reason="Invalid pickup status",
            )
            return

        await websocket.send_json({
            "status": True,
            "pickup_data": {
                "pickup_id": pickup_id,
                "status": initial_status,
            },
        })

        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def pickup_status_listener(event):
            data = event.data

            if isinstance(data, dict):
                status = data.get("status")
            elif isinstance(data, str):
                status = data
            else:
                return

            if not isinstance(status, str):
                return

            asyncio.run_coroutine_threadsafe(
                queue.put(status),
                loop,
            )

        listener = pickup_status_db.listen(
            pickup_status_listener
        )

        while True:
            pickup_status = await queue.get()

            await websocket.send_json({
                "status": True,
                "pickup_data": {
                    "pickup_id": pickup_id,
                    "status": pickup_status,
                },
            })

    except asyncio.TimeoutError:
        await websocket.close(
            code=1008,
            reason="Authentication timeout",
        )

    except WebSocketDisconnect:
        print("Disconnected user:", user_id)

    finally:
        if listener is not None:
            listener.close()