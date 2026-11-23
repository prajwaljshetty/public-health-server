# OS :
import asyncio
import uuid

# Date Time :
from datetime import datetime, timezone

# HTTP :
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

# Firebase :
from firebase_admin import db
from google.cloud.firestore_v1.base_query import FieldFilter

# Database :
from app.firebase import firestore_db, realtime_db

# Authentication :
from app.auth import (
    create_access_token,
    create_refresh_token,
    validate_token,
    get_current_user,
    get_refresh_token,
)

# Password :
from app.hasher import hash_password, verify_password

# Models :
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PHONE_NUMBER_ALREADY_REGISTERED"
        )

    user_id = str(uuid.uuid4())

    password = hash_password(user.password)

    firestore_db.collection("households").document(user_id).set({
        "user_id": user_id,
        "user_name": user.username,
        "role": "household",
        "phoneno": user.phoneno,
        "password": password,
    })

    access_token = create_access_token(user_id =user_id , role = "household")
    refresh_token = create_refresh_token(user_id = user_id , role = "household")

    return {
        "status": True,
        "message": "Account created successfully",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

@router.post("/login")
def login(login_data: HouseholdLogin):

    user = firestore_db.collection("households").where(
        filter=FieldFilter("phoneno", "==", login_data.phoneno)
    ).limit(1).stream()

    existing_user = next(user, None)

    if existing_user is None:
        raise HTTPException(
            status_code=404,
            detail="USER_NOT_FOUND"
        )

    user_data = existing_user.to_dict() or {}

    if user_data["role"] != "household":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    if not verify_password(
        hashed_password=user_data["password"],
        password=login_data.password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INCORRECT_PASSWORD",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_id = user_data["user_id"]
    refresh_token = create_refresh_token(user_id = user_id , role = "household")
    access_token = create_access_token(user_id = user_id , role = "household")

    return {
        "status": True,
        "message": "Login successful",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

@router.post("/refresh")
def get_access_token(
    payload: dict = Depends(get_refresh_token),
):

    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NO_LONGER_EXIST",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_data = user.to_dict() or {}

    if payload["role"] != "household" or user_data["role"] != "household":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

   

    return {
        "status": True,
        "message": "Access token refreshed successfully",
        "access_token" : create_access_token(
            user_id=user_id,
            role="household"
        ),
        "token_type": "bearer",
        "expires_in": 900,
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):

    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "household" or user_data.get("role") != "household":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    household_state = realtime_db.reference(
        f"households/{user_id}"
    ).get() or {}

    return {
        "status": True,
        "message": "User data fetched successfully",
        "user_data": {
            "user_id": user_id,
            "role": "household",
            "user_name": user_data.get("user_name"),
            "phoneno": user_data.get("phoneno"),
            "pickup_status": household_state.get("status", "idle"),
        },
    }

# Pickuo :
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
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "household"
        or user_data.get("role") != "household"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    pickup_id = str(uuid.uuid4())
    pickup_time = household_request_data.time.isoformat()
    requested_at = datetime.now(timezone.utc).isoformat()

    household_ref = realtime_db.reference(
        f"households/{user_id}"
    )

    def claim_household(current_data):

        current_data = current_data or {}

        if current_data.get("status", "idle") != "idle":
            return current_data

        current_data.update({
            "status": "requested",
            "code": "-1",
            "pickup_id": pickup_id,
        })

        return current_data

    claimed_household = household_ref.transaction(
        claim_household
    )

    if (
        not claimed_household
        or claimed_household.get("pickup_id") != pickup_id
        or claimed_household.get("status") != "requested"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HOUSEHOLD_ALREADY_HAS_ACTIVE_PICKUP"
        )

    pickup_data = {
        "pickup_id": pickup_id,
        "household_id": user_id,
        "time": pickup_time,
        "coordinates": {
            "latitude": household_request_data.coordinate.latitude,
            "longitude": household_request_data.coordinate.longitude,
        },
        "qna": household_request_data.qna,
    }

    audit_data = {
        "household_id": user_id,
        "pickup_id": pickup_id,
        "requested_at": requested_at,
    }

    try:

        realtime_db.reference().update({
            f"pickups/pickup_data/{pickup_id}": pickup_data,
            f"pickups/requested/{pickup_id}": True,
            f"audit/requested/{pickup_id}": audit_data,
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
                })

            return current_data

        household_ref.transaction(rollback_household)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_REQUEST_FAILED"
        )

    return {
        "status": True,
        "message": "Pickup requested successfully",
        "pickup_id": pickup_id,
        "requested_at": requested_at,
    }

@router.get("/pickup/data")
def get_pickup_data(payload: dict = Depends(get_current_user)):

    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload["role"] != "household"
        or user_data.get("role") != "household"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
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
                "coordinates": stored_pickup.get("coordinates"),
                "qna": stored_pickup.get("qna", []),
            }

    return {
        "status": True,
        "message": "Pickup data fetched successfully",
        "pickup_status": household_state.get("status", "idle"),
        "pickup_id": pickup_id,
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
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "household"
        or user_data.get("role") != "household"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    pickup_id = register_data.pickup_id
    code = register_data.code

    if not code.isdigit() or len(code) != 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PICKUP_CODE_MUST_CONTAIN_EXACTLY_SIX_DIGITS"
        )

    household_ref = realtime_db.reference(
        f"households/{user_id}"
    )

    pickup_data = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    ).get()

    if not pickup_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_NOT_FOUND"
        )

    if pickup_data.get("household_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="UNAUTHORIZED_PICKUP"
        )

    code_hash = hash_password(code)

    def register_household_code(current_data):

        if not current_data:
            return current_data

        if (
            current_data.get("pickup_id") != pickup_id
            or current_data.get("status") != "accepted"
        ):
            return current_data

        current_data["code"] = code_hash

        return current_data

    registered_data = household_ref.transaction(
        register_household_code
    )

    if (
        not registered_data
        or registered_data.get("pickup_id") != pickup_id
        or registered_data.get("status") != "accepted"
        or not verify_password(
            code,
            registered_data.get("code", "")
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_NOT_AVAILABLE_FOR_CODE_REGISTRATION"
        )

    return {
        "status": True,
        "message": "Pickup code registered successfully",
        "pickup_id": pickup_id
    }

@router.get("/points")
def get_points(payload: dict = Depends(get_current_user)):

    user_id = payload["sub"]

    user = firestore_db.collection("households").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "household"
        or user_data.get("role") != "household"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    household_data = realtime_db.reference(
        f"households/{user_id}"
    ).get() or {}

    return {
        "status": True,
        "message": "Points fetched successfully",
        "points": household_data.get("points", 0)
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

        if payload.get("role") != "household":
            await websocket.close(
                code=1008,
                reason="Insufficient permissions",
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

                if (
                    data.get("pickup_id") != pickup_id
                    and not (
                        data.get("status") == "idle"
                        and data.get("pickup_id") is None
                    )
                ):
                    continue

                await websocket.send_json({
                    "status": True,
                    "pickup_data": {
                        "pickup_id": data.get("pickup_id"),
                        "status": data.get("status", "idle"),
                        "code": data.get("code", "-1"),
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
