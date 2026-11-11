
import asyncio
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from firebase_admin import db
from google.cloud.firestore_v1.base_query import FieldFilter

from app.firebase import firestore_db, realtime_db
from app.auth import (
    create_access_token,
    create_refresh_token,
    validate_token,
    get_current_user,
    get_refresh_token,
)
from app.hasher import hash_password, verify_password
from app.models.household import (
    HousholdCreate,
    HouseholdLogin,
    HouseholdRequestData,
    RegisterCode,
)

router = APIRouter()

@router.post("/create")
def create(user: HousholdCreate):
    users = firestore_db.collection("households").where(
        filter=FieldFilter("phoneno", "==", user.phoneno)
    ).stream()

    if next(users, None):
        return {
            "status": False,
            "message": "PHONE_NUMBER_ALREADY_REGISTERED",
            "user_id": None,
        }

    user_id = str(uuid.uuid4())
    password = hash_password(user.password)

    firestore_db.collection("households").document(user_id).set({
        "user_id": user_id,
        "user_name": user.username,
        "userid": user_id,
        "role": "household",
        "username": user.username,
        "phoneno": user.phoneno,
        "password": password,
    })

    access_token = create_access_token(user_id=user_id)
    refresh_token = create_refresh_token(user_id=user_id)

    return {
        "status": True,
        "message": "Account created successfully",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

@router.post("/login")
def login(user: HouseholdLogin):
    users = firestore_db.collection("households").where(
        filter=FieldFilter("phoneno", "==", user.phoneno)
    ).limit(1).stream()

    existing_user = next(users, None)

    if existing_user is None:
        return {
            "status": False,
            "message": "USER_NOT_FOUND",
            "user_id": None,
        }

    user_data = existing_user.to_dict()

    if not verify_password(
        hashed_password=user_data["password"],
        password=user.password,
    ):
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "user_id": None,
        }

    user_id = user_data["user_id"]
    refresh_token = create_refresh_token(user_id=user_id)
    access_token = create_access_token(user_id=user_id)

    return {
        "status": True,
        "message": "Login successful",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):
    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "user_data": None,
        }

    user_data = user.to_dict() or {}

    household_state = realtime_db.reference(
        f"households/{user_id}"
    ).get() or {}

    return {
        "status": True,
        "message": "User data fetched successfully",
        "user_data": {
            "user_id": user_id,
            "role": "household",
            "user_name": user_data["user_name"],
            "phoneno": user_data["phoneno"],
            "pickup_status": household_state.get("status", "idle"),
        },
    }

@router.post("/pickup/request")
def request_pickup(
    household_request_data: HouseholdRequestData,
    payload: dict = Depends(get_current_user),
):
    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND",
        )

    pickup_id = str(uuid.uuid4())
    pickup_time = household_request_data.time.isoformat()

    household_ref = realtime_db.reference(f"households/{user_id}")

    def claim_household(current_data):
        current_data = current_data or {}

        current_status = current_data.get("status", "idle")

        if current_status != "idle":
            return current_data

        current_data.update({
            "status": "requested",
            "code": "-1",
            "pickup_id": pickup_id,
            "worker_id": None,
        })

        return current_data

    claimed_household = household_ref.transaction(claim_household)

    if (
        not claimed_household
        or claimed_household.get("pickup_id") != pickup_id
        or claimed_household.get("status") != "requested"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HOUSEHOLD_ALREADY_HAS_ACTIVE_PICKUP",
        )

    pickup_data = {
        "pickup_id": pickup_id,
        "household_id": user_id,
        "time": pickup_time,
        "coordinate": {
            "latitude": household_request_data.coordinate.latitude,
            "longitude": household_request_data.coordinate.longitude,
        },
        "qna": household_request_data.qna,
    }

    try:
        realtime_db.reference().update({
            f"pickups/pickup_data/{pickup_id}": pickup_data,
            f"pickups/requested/{pickup_id}": True,
        })

    except Exception:
        def rollback_household(current_data):
            if (
                current_data
                and current_data.get("pickup_id") == pickup_id
                and current_data.get("status") == "requested"
            ):
                current_data.update({
                    "status": "idle",
                    "code": "-1",
                    "pickup_id": None,
                    "worker_id": None,
                })

            return current_data

        household_ref.transaction(rollback_household)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_REQUEST_FAILED",
        )

    return {
        "status": True,
        "message": "Pickup requested successfully",
        "pickupid": pickup_id,
    }

@router.get("/pickup/data")
def get_pickup_data(payload: dict = Depends(get_current_user)):
    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND",
        )

    household_state = realtime_db.reference(
        f"households/{user_id}"
    ).get() or {}

    pickup_id = household_state.get("pickup_id")
    pickup_data = None

    if pickup_id:
        stored_pickup = realtime_db.reference(
            f"pickups/pickup_data/{pickup_id}"
        ).get()

        if stored_pickup:
            household_profile = user.to_dict() or {}
            pickup_data = {
                "pickup_id": pickup_id,
                "user_id": user_id,
                "user_name": household_profile.get("user_name"),
                "time": stored_pickup.get("time"),
                "coordinate": stored_pickup.get("coordinate"),
                "qna": stored_pickup.get("qna", []),
            }

    return {
        "status": True,
        "message": "Pickup data fetched successfully",
        "pickup_status": household_state.get("status", "idle"),
        "pickup_id": pickup_id,
        "code": household_state.get("code", "-1"),
        "pickup_data": pickup_data,
    }

@router.post("/pickup/registercode")
def register_code(
    register_data: RegisterCode,
    payload: dict = Depends(get_current_user),
):
    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND",
        )

    pickup_id = register_data.pickup_id
    code = register_data.code

    if not code.isdigit() or len(code) != 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PICKUP_CODE_MUST_CONTAIN_EXACTLY_SIX_DIGITS",
        )


    household_ref = realtime_db.reference(f"households/{user_id}")

    pickup_data = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    ).get()

    if not pickup_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_NOT_FOUND",
        )


    if pickup_data.get("household_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="UNAUTHORIZED_PICKUP",
        )
    
    def register_household_code(current_data):
        if not current_data:
            return current_data

        if (
            current_data.get("pickup_id") != pickup_id
            or current_data.get("status") != "accepted"
        ):
            return current_data

        current_data["code"] = code
        current_data["status"] = "accepted"

        return current_data

    registered_data = household_ref.transaction(
        register_household_code
    )

    if (
        not registered_data
        or registered_data.get("pickup_id") != pickup_id
        or registered_data.get("status") != "accepted"
        or registered_data.get("code") != code
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_NOT_AVAILABLE_FOR_CODE_REGISTRATION",
        )

    try:
        realtime_db.reference().update({
            f"pickups/assigned/{pickup_id}": None,
            f"pickups/accepted/{pickup_id}": True,
        })

    except Exception:
        def rollback_code(current_data):
            if (
                current_data
                and current_data.get("pickup_id") == pickup_id
                and current_data.get("status") == "accepted"
                and current_data.get("code") == code
            ):
                current_data["status"] = "assigned"
                current_data["code"] = "-1"

            return current_data

        household_ref.transaction(rollback_code)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_CODE_REGISTRATION_FAILED",
        )

    return {
        "status": True,
        "message": "Pickup code registered successfully",
    }

@router.post("/refresh")
def get_access_token(
    request_data: dict = Depends(get_refresh_token),
):
    user_id = request_data["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NO_LONGER_EXIST",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user_id=user_id)

    return {
        "status": True,
        "message": "Access token refreshed successfully",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 900,
    }

@router.websocket("/pickup/status/{pickup_id}")
async def pickup_status_stream(
    websocket: WebSocket,
    pickup_id: str,
):
    await websocket.accept()

    listener = None
    receive_task = None
    send_task = None

    try:
        token = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=10,
        )

        payload = validate_token(token, "access")

        if not payload:
            await websocket.close(
                code=1008,
                reason="Invalid access token",
            )
            return

        user_id = payload["sub"]

        household_ref = realtime_db.reference(
            f"households/{user_id}"
        )

        initial_data = household_ref.get()

        if (
            not initial_data
            or initial_data.get("pickup_id") != pickup_id
        ):
            await websocket.send_json({
                "status": False,
                "message": "Unauthorized or pickup not found",
                "pickup_data": {},
            })

            await websocket.close(
                code=1008,
                reason="Unauthorized pickup",
            )
            return

        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def household_listener(event):
            data = event.data

            if not isinstance(data, dict):
                data = household_ref.get() or {}

            if isinstance(data, dict):
                asyncio.run_coroutine_threadsafe(
                    queue.put(data),
                    loop,
                )

        listener = household_ref.listen(household_listener)

        await websocket.send_json({
            "status": True,
            "pickup_data": {
                "pickup_id": initial_data.get("pickup_id"),
                "status": initial_data.get("status", "idle"),
                "code": initial_data.get("code", "-1"),
                "worker_id": initial_data.get("worker_id"),
            },
        })

        async def receive():
            while True:
                message = await websocket.receive_text()

                if message == "logout":
                    return

        async def send_updates():
            while True:
                data = await queue.get()

                if data.get("pickup_id") not in (pickup_id, None):
                    continue

                print(
                {
                    "status": True,
                    "pickup_data": {
                        "pickup_id": data.get("pickup_id"),
                        "status": data.get("status", "idle"),
                        "code": data.get("code", "-1"),
                        "worker_id": data.get("worker_id"),
                    },
                }
                )
                await websocket.send_json({
                    "status": True,
                    "pickup_data": {
                        "pickup_id": data.get("pickup_id"),
                        "status": data.get("status", "idle"),
                        "code": data.get("code", "-1"),
                        "worker_id": data.get("worker_id"),
                    },
                })

        receive_task = asyncio.create_task(receive())
        send_task = asyncio.create_task(send_updates())

        done, pending = await asyncio.wait(
            [receive_task, send_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        await asyncio.gather(
            *pending,
            return_exceptions=True,
        )

        for task in done:
            task.result()

    except asyncio.TimeoutError:
        await websocket.close(
            code=1008,
            reason="Authentication timeout",
        )

    except WebSocketDisconnect:
        pass

    finally:
        for task in (receive_task, send_task):
            if task is not None and not task.done():
                task.cancel()

        if listener is not None:
            listener.close()
