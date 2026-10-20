from fastapi import APIRouter

# Firebase :
from firebase_admin import db
from app.firebase import firestore_db , realtime_db

# HTTP :
from fastapi import Depends , HTTPException, status

# Token Creation and Validations :
from app.auth import (
    create_acess_token ,
    create_refresh_token ,
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
    access_token = create_acess_token(user_id= user_id)

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

    user_id = user_data["user_id"]

    # Check password with Hashed Password
    if not verify_password(hashed_password= user_data["password"] , password = user.password):
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "user_id": None
        }
    
    # Generate Access Token
    access_token = create_acess_token(user_id= user_id)

    # Generate Refresh Token
    refresh_token = create_refresh_token(user_id= user_id)

    # Return response
    return {
        "status": True,
        "message": "Login successful",
        "user_id": user_id,
        "access_token" : access_token ,
        "refresh_token" : refresh_token
    }


from fastapi import APIRouter, Depends, HTTPException, status
import uuid

@router.post("/requestpickup")
async def request_pickup(
    household_request_data: HouseholdRequestData,
    user_data: dict = Depends(get_current_user),
):
    # Get authenticated household ID from the JWT
    user_id = user_data["sub"]

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
        "pickups/pickup_requests"
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

    return {
        "status": True,
        "message": "Pickup requested successfully",
        "pickupid": pickup_id,
    }

@router.get("/data")
def get_data(user_data: dict = Depends(get_current_user)):

    # Get user ID
    user_id = user_data["sub"]

    # Check user exists
    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "user_data": None
        }

    # Get user data from Firestore
    household_data = user.to_dict()

    # Check whether the user already has an active pickup request
    pickups = realtime_db.reference(
        "pickups/pickup_requests"
    ).get()

    has_active_pickup = False

    if pickups:
        for pickup in pickups.values():
            if pickup.get("user_id") == user_id:
                has_active_pickup = True
                break

    # Return household data
    return {
        "status": True,
        "message": "User data fetched successfully",
        "user_data": {
            "user_id": user_id,
            "role": "household",
            "user_name": household_data["user_name"],
            "phoneno": household_data["phoneno"],
            "has_active_pickup": has_active_pickup
        }
    }

@router.get("/pickupdata")
def get_pickup_data(user_data : dict = Depends(get_current_user)):
    # Get household ID
    user_id = user_data["sub"]

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
        realtime_db.reference("pickups/pickup_requests")
        .order_by_child("user_id")
        .equal_to(user_id)
        .get()
    )

    # Pickup data does not exist
    if not pickups:
        return {
            "status": True,
            "message": "No pickup request found",
            "pickupdata": None
        }

    pickupdata = next(iter(pickups.values()))

    # Return pickup details
    return {
        "status": True,
        "message": "Pickup data fetched successfully",
        "pickupdata": pickupdata
    }

@router.post("/refresh")
def get_access_token(
    request_data: dict = Depends(get_refresh_token)
):
    # Get user ID from validated refresh token
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
    access_token = create_acess_token(user_id=user_id)

    return {
        "status": True,
        "message": "Access token refreshed successfully",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 900
    }
