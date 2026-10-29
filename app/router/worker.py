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

    async def receive():
        while True :
            message = await websocket.receive_text()
            if message == "logout" : 
                return

    async def pickup():
        while True:
            pickup_data = await queue.get()

            pickup_list = []
        
            for pickupid, pickup in pickup_data.items():

                pickup_userid = pickup["user_id"]

                user = firestore_db.collection("households").document(
                    pickup_userid
                ).get()

                if user.exists:

                    userdata = user.to_dict()

                    pickup_item = {
                        "pickupid": pickupid,
                        "user_id": pickup_userid,
                        "user_name": userdata["user_name"],
                        "time": pickup["time"],
                        "coordinates": pickup["coordinate"],
                        "qna": pickup["qna"],
                    }

                    pickup_list.append(pickup_item)

            await websocket.send_json(pickup_list)

    listener = pickup_DB.listen(pickup_listener)

    message_task = asyncio.create_task(receive())
    pickup_task = asyncio.create_task(pickup())

    try:
        done, pending = await asyncio.wait(
            [message_task, pickup_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            task.result()

        if message_task in done:
            print("Worker logged out:", userid)

    except WebSocketDisconnect:
        print("Disconnected user:", userid)

    finally:
        message_task.cancel()
        pickup_task.cancel()
        
        await asyncio.gather(
            message_task, pickup_task,
            return_exceptions=True
        )
        listener.close()