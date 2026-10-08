from fastapi import APIRouter , WebSocket, WebSocketDisconnect

# Model :
from app.models.worker import WorkerLogin

# Firebase :
from firebase_admin import db
from app.firebase import firestore_db , realtime_db

# Asychronus :
import asyncio

# Filter :
from google.cloud.firestore_v1.base_query import FieldFilter


router = APIRouter()


@router.post("/login")
def login(user : WorkerLogin):

    # 1. Check whether user exists in database
    users = firestore_db.collection('workers').where(
    filter=FieldFilter("workerid", "==", user.workerid)
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

@router.websocket("/pickups/{userid}")
async def pickupstream(websocket: WebSocket, userid: str):

    user = firestore_db.collection("workers").document(userid).get()

    if not user.exists:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    print("Connected user:", userid)

    pickup_DB = db.reference("pickups/pickup_requests")

    queue = asyncio.Queue()

    loop = asyncio.get_running_loop()

    def pickup_listener(event):
        pickup_data = pickup_DB.get()

        if pickup_data is None:
            pickup_data = {}

        asyncio.run_coroutine_threadsafe(
            queue.put(pickup_data),
            loop
        )

    listener = pickup_DB.listen(pickup_listener)

    try:
        while True:

            pickup_data = await queue.get()

            pickup_list = []

            for pickupid, pickup in pickup_data.items():

                pickup_userid = pickup["userid"]

                user = firestore_db.collection("households").document(
                    pickup_userid
                ).get()

                if user.exists:

                    userdata = user.to_dict()

                    pickup_item = {
                        "pickupid": pickupid,
                        "userid": pickup_userid,
                        "username": userdata["username"],
                        "time": pickup["time"],
                        "coordinates": pickup["coordinates"],
                        "qna": pickup["qna"],
                    }

                    pickup_list.append(pickup_item)

            await websocket.send_json(pickup_list)

    except WebSocketDisconnect:
        print("Disconnected user:", userid)