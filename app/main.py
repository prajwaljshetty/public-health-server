from fastapi import FastAPI

# Routers :
from app.router import household

# Firebase
from app.firebase import firestore_db , realtime_db

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Server is running"}

app.include_router(
    household.router,
    prefix="/household"
)


@app.get("/data/{user_id}")
def getdata(user_id: str):

    # 1. Check whether user exists in database
    user = firestore_db.collection("users").document(user_id).get()

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
            if pickup.get("userid") == user_id:
                has_active_pickup = True
                break

    # 4. Return user data
    return {
        "status": True,
        "message": "User data fetched successfully",
        "userdata": {
            "userid": userdata["userid"],
            "role": userdata["role"],
            "username": userdata["username"],
            "phoneno": userdata["phoneno"],
            "hasActivePickup": has_active_pickup
        }
    }