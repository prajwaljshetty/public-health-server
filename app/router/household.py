from fastapi import APIRouter, UploadFile, File, Form
import os
import json

# Firebase
from app.firebase import firestore_db , realtime_db

# Unique :
import uuid

# User Model :
from app.models.user import UserRegister , UserLogin 


router = APIRouter()

# Post :

@router.post("/create")
def create(user: UserRegister):

    # 1. Check whether user already exists
    users = firestore_db.collection("users").where(
        "phoneno", "==", user.phoneno
    ).limit(1).stream()

    if next(users, None):
        return {
            "status": False,
           "message": "PHONE_NUMBER_ALREADY_REGISTERED",
            "uid": None
        }

    # 2. Generate uid
    user_id = str(uuid.uuid4())

    # 3. Save user
    firestore_db.collection("users").document(user_id).set({
        "userid": user_id,
        "role" :user.role,
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
def login(user: UserLogin):

    # 1. Find user by phone number
    users = firestore_db.collection("users").where(
        "phoneno", "==", user.phoneno
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
    user = firestore_db.collection("users").document(userid).get()

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
    os.makedirs("uploads/users", exist_ok=True)

    # 4. Save/replace user's image
    image_path = f"uploads/users/{userid}.jpg"

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



