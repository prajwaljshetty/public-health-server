from fastapi import APIRouter

# Model :
from app.models.worker import WorkerLogin

# Firebase :
from app.firebase import firestore_db , realtime_db


router = APIRouter()


@router.post("/login")
def login(user : WorkerLogin):

    # 1. Check whether user exists in database
    users = firestore_db.collection('workers').where(
        "workerid","==",user.workerid
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

@router.get("/data/{userid}")
def getdata(userid : str):

    # check whether user exist
    user = firestore_db.collection("workers").document(userid).get()

    # return if user not exist
    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "userdata": None
        }

    # extract data
    userdata = user.to_dict()

    # 4. Return user data
    return {
            "status": True,
            "message": "User data fetched successfully",
            "userdata": {
            "userid": userdata["userid"],
            "role": userdata["role"],
            "username": userdata["username"],
            "phoneno": userdata["phoneno"],
        }}