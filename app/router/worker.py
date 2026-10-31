from fastapi import APIRouter , WebSocket, WebSocketDisconnect

# Model :
from app.models.worker import WorkerRegister , WorkerLogin , PickupAcceptanceRequest

# Firebase :
from firebase_admin import db
from app.firebase import firestore_db , realtime_db

# Asychronus :
import asyncio

# Filter :
from google.cloud.firestore_v1.base_query import FieldFilter

# HTTP :
from fastapi import Depends , HTTPException, status

# Unique :
import uuid

# Token Creation and Validations :
from app.auth import (
    create_access_token ,
    create_refresh_token ,
    get_current_user , 
    get_refresh_token ,
    validate_token
)

# Password Hasher :
from app.hasher import (
    hash_password ,
    verify_password ,
)

router = APIRouter()

@router.post("/createaccount")
def create_account(worker: WorkerRegister):

    # Check whether worker already exists
    users = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker.worker_id
        )
    ).limit(1).stream()

    if next(users, None):
        return {
            "status": False,
            "message": "WORKER_ALREADY_EXISTS",
            "user_id": None
        }

    # Generate user ID
    user_id = str(uuid.uuid4())

    # Hash password
    password = hash_password(worker.password)

    # Save worker
    firestore_db.collection("workers").document(user_id).set({
        "user_id": user_id,
        "worker_id": worker.worker_id,
        "user_name": worker.user_name,
        "phoneno": worker.phoneno,
        "password": password,
        "role": "worker"
    })

    # Generate Access Token
    access_token = create_access_token(user_id=user_id)

    # Generate Refresh Token
    refresh_token = create_refresh_token(user_id=user_id)

    # Return response
    return {
        "status": True,
        "message": "Account created successfully",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@router.post("/login")
def login(user: WorkerLogin):
    
    # Find worker by worker ID
    users = firestore_db.collection("workers").where(
        filter=FieldFilter("worker_id", "==", user.worker_id)
    ).limit(1).stream()


    existing_user = next(users, None)

    # User does not exist
    if existing_user is None:
        return {
            "status": False,
            "message": "USER_NOT_FOUND",
            "user_id": None
        }

    user_data = existing_user.to_dict()

    # Check password with Hashed Password
    if not verify_password(hashed_password = user_data["password"] , password = user.password):
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "user_id": None
        }

    user_id = user_data['user_id']

    # Generate tokens
    access_token = create_access_token(user_id=user_id)
    refresh_token = create_refresh_token(user_id=user_id)

    return {
        "status": True,
        "message": "Login successful",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):
    # Get user ID from JWT payload
    user_id = payload["sub"]

    # Fetch worker document
    user = firestore_db.collection("workers").document(user_id).get()

    # Check whether the worker exists
    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "user_data": None
        }

    # Extract worker data
    user_data = user.to_dict()

    return {
        "status": True,
        "message": "User data fetched successfully",
        "user_data": {
            "user_id": user_data["user_id"],
            "role": user_data["role"],
            "user_name": user_data["user_name"],
            "phoneno": user_data["phoneno"]
        }
    }

@router.get("/accept")
async def accept_pickup(payload: dict = Depends(get_current_user) , pickup_data = PickupAcceptanceRequest):

    # Get user ID from JWT payload
    user_id = payload["sub"]

    # Find worker by worker ID
    user = firestore_db.collection("workers").document(user_id).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
        }

    


    return {
        "status": True,
        "message": "No pickup request found",
        "pickup_data": None
    }
    
@router.post("/refresh")
def get_access_token(
    request_data: dict = Depends(get_refresh_token)
):
    # Get user ID
    user_id = request_data["sub"]

    # Check whether the user exists
    user = firestore_db.collection("workers").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NO_LONGER_EXIST",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate a new access token
    access_token = create_access_token(user_id=user_id)

    return {
        "status": True,
        "message": "Access token refreshed successfully",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 900
    }

@router.websocket("/pickups")
async def pickup_stream(websocket: WebSocket ):

    await websocket.accept()

    user_id = None

    try :
        token = await asyncio.wait_for(
            websocket.receive_text() ,
            timeout = 10
        )

        payload = validate_token(token = token , tokentype = "access")

        if not payload :
            await websocket.close(
                code=1008,
                reason="Invalid access token",
            )
            return

        user_id = payload["sub"]

        print("Connected user:", user_id)

        pickup_DB = db.reference("pickups/requests")

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

                    user =  await asyncio.to_thread(
                        firestore_db.collection("households").document(
                        pickup_userid).get
                    )
                    
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

        try :
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
                print("Worker logged out:", user_id)

        except WebSocketDisconnect:
            print("Disconnected user:", user_id)
            
        finally:
            message_task.cancel()
            pickup_task.cancel()
            
            await asyncio.gather(
                message_task, pickup_task,
                return_exceptions=True
            )
            await asyncio.to_thread(listener.close)

    except asyncio.TimeoutError:
            await websocket.close(
                code=1008,
                reason="Authentication timeout",
            )

