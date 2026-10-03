from fastapi import APIRouter

# Unique :
import uuid

# User Model :
from app.models.user import UserRegister , UserLogin 
from app.models.pickup import PickupRequest

router = APIRouter()

# Post :
@router.post("/register")
def register(user: UserRegister):

    # 1. Generate userid
    user_id = str(uuid.uuid4())

    # 2. Check whether user already exists
    # Database logic will be added later

    # 3. Save user
    # Database logic will be added later

    # 4. Return created user
    return {
        "userid": user_id
    }

@router.post("/login")
def login(user: UserLogin):

    # 1. Check whether user exists in database
    # 2. Verify the provided credentials
    # 3. If credentials are invalid → return error

    user_id = "xyz"

    return {
        "userid": user_id,
    }

@router.post("/requestpickup")
def request_pickup(pickup: PickupRequest):

    # 1. Generate pickup id

    # 2. Check whether user exists in database
    # Database logic will be added later

    # 3. Save pickup request
    # Database logic will be added later

    # 4. Return pickup id

    pickup_id = "xyz"

    return {
        "pickup_id": pickup_id
    }


# Get :

@router.get("/data/{user_id}")
def getdata(user_id: str):

    # 1. Check whether user exists in database
    # 2. Get user data from database

    userdata = {
        "userid": user_id,
        "username": "Public Health",
        "phoneno": "9999999999"
    }

    return {
        "userdata": userdata
    }
