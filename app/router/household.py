from fastapi import APIRouter, UploadFile, File, Form
import os
import json
from firebase_admin import db

# Firebase :
from app.firebase import firestore_db , realtime_db

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

    # 1. Check whether user already exists
    users = firestore_db.collection("households").where(
            filter=FieldFilter(
                "phoneno",
                "==",
                user.phoneno
    )).stream()

    if next(users, None):
        return {
            "status": False,
            "message": "PHONE_NUMBER_ALREADY_REGISTERED",
            "uid": None
        }

    # 2. Generate uid
    user_id = str(uuid.uuid4())

    # 3. Save user
    firestore_db.collection("households").document(user_id).set({
        "userid": user_id,
        "username": user.username,
        "phoneno": user.phoneno,
        "password": user.password
    })

    print(user.username)


    # 4. Return response
    return {
        "status": True,
        "message": "Account created successfully",
        "uid": user_id
    }

@router.post("/login")
def login(user: HouseholdLogin):

    # 1. Find user by phone number
    users = firestore_db.collection("households").where(
        filter=FieldFilter(
            "phoneno",
            "==",
            user.phoneno
        )
    ).limit(1).stream()

    existing_user = next(users, None)

    # 2. User does not exist
    if existing_user is None:
        return {
            "status": False,
            "message": "USER_NOT_FOUND",
            "uid": None
        }

    # 3. Get user data
    user_data = existing_user.to_dict()

    # 4. Check password
    if user_data["password"] != user.password:
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "uid": None
        }

    # 5. Login successful
    return {
        "status": True,
        "message": "Login successful",
        "uid": user_data["userid"]
    }

from datetime import timezone
import uuid

@router.post("/requestpickup")
async def request_pickup(
    household_request_data: HouseholdRequestData
):
    # 1. Check whether the household exists
    user = firestore_db.collection("households").document(
        household_request_data.userid
    ).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "pickupid": None
        }

    # 2. Generate pickup ID
    pickup_id = str(uuid.uuid4())


    # 4. Convert datetime to a string
    pickup_time = household_request_data.time.isoformat()

    # 5. Save pickup data
    realtime_db.reference("pickups/pickup_requests").child(
        pickup_id
    ).set({
        "pickupid": pickup_id,
        "userid": household_request_data.userid,
        "time": pickup_time,
        "coordinate": {
            "latitude": household_request_data.coordinate.latitude,
            "longitude": household_request_data.coordinate.longitude,
        },
        "qna": household_request_data.qna
    })

    # 6. Return response
    return {
        "status": True,
        "message": "Pickup requested successfully",
        "pickupid": pickup_id
    }


@router.get("/data/{userid}")
def getdata(userid: str):

    # 1. Check whether user exists in database
    user = firestore_db.collection("households").document(userid).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "userdata": None
        }

    # 2. Get user data from database
    userdata = user.to_dict()

    # 3. Check whether user already has a pickup request
    pickups = realtime_db.reference(
        "pickups/pickup_requests"
    ).get()

    has_active_pickup = False

    if pickups:
        for pickup in pickups.values():
            if pickup.get("userid") == userid:
                has_active_pickup = True
                break

    # 4. Return user data
    return {
        "status": True,
        "message": "User data fetched successfully",
        "userdata": {
            "userid": userdata["userid"],
            "role": 'household',
            "username": userdata["username"],
            "phoneno": userdata["phoneno"],
            "hasActivePickup": has_active_pickup
        }
    }



