from fastapi import APIRouter , WebSocket, WebSocketDisconnect

# Model :
from app.models.worker import WorkerLogin

# Firebase :
from app.firebase import firestore_db , realtime_db

# Asychronus :
import asyncio


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

@router.websocket("/pickups/{userid}")
async def pickupstream(websocket: WebSocket, userid: str):

    user = firestore_db.collection("workers").document(userid).get()

    if not user.exists:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    print("Connected user:", userid)

    pickup_data = [
            {
                "pickupid": "4d3a6f48-80fc-4148-8c0b-7b867d553297",
                "userid": "1737d704-1380-4bd2-a1dc-d144cf93e658",
                "time": "2026-10-07 16:07:33.187130",
                "coordinates": {
                    "latitude": 13.0647,
                    "longitude": 74.9951
                },
                "qna": [1, 0, 1],
            },
            {
                "pickupid": "7a1b2c3d-4567-8901-abcd-ef1234567890",
                "userid": "2858e815-2491-5cd3-b2ee-e255df74f769",
                "time": "2026-10-08 14:30:00",
                "coordinates": {
                    "latitude": 13.0712,
                    "longitude": 74.9918
                },
                "qna": [1, 1, 0],
            },
        ]

    try:
        while True:
            await websocket.send_json(pickup_data)
            await asyncio.sleep(5)
            message = await websocket.receive_text()
            if message == "logout":
                print("User logged out : ", userid)
                break

    except WebSocketDisconnect:
        print("Disconnected user : ", userid)

