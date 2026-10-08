from fastapi import APIRouter, UploadFile, File, Form
import os
import json

# Firebase :
from app.firebase import firestore_db , realtime_db

# Unique :
import uuid

# User Model :
from app.models.household import HousholdCreate , HouseholdLogin 

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

@router.post("/requestpickup")
async def request_pickup(
    userid: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    qna : str = Form(...),
    image: UploadFile = File(...)
):
    # 1. Check whether user exists
    user = firestore_db.collection("households").document(userid).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "pickupid": None
        }

    # 2. Generate pickup ID
    pickup_id = str(uuid.uuid4())

    qna = [int(x) for x in qna.split(",")]

    # 3. Create user image directory
    os.makedirs("uploads/households", exist_ok=True)

    # 4. Save/replace user's image
    image_path = f"uploads/households/{userid}.jpg"

    with open(image_path, "wb") as file:
        file.write(await image.read())

    # 5. Save pickup data
    realtime_db.reference("pickups/pickup_requests").child(pickup_id).set({
        "pickupid": pickup_id,
        "userid": userid,
        "time": time,
        "coordinates": {
            "latitude": latitude,
            "longitude": longitude
        },
        "qna": qna
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



