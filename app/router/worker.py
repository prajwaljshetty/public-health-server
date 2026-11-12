# OS :
import asyncio
import re
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
from app.firebase import db, firestore_db, realtime_db

# Filter :
from google.cloud.firestore_v1 import transactional
from google.cloud.firestore_v1.base_query import FieldFilter

# Models :
from app.models.worker import (
    PickupAcceptanceRequest,
    WorkerLogin,
    WorkerRegister,
)

# Authentication :
from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_refresh_token,
    validate_token,
)

# Password :
from app.hasher import (
    hash_password,
    verify_password,
)

router = APIRouter()


@router.post("/login")
def login(login_data: WorkerLogin):

    user = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            login_data.worker_id.strip().upper()
        )
    ).limit(1).stream()

    existing_user = next(user, None)

    if not existing_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NOT_FOUND",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_data = existing_user.to_dict() or {}

    if user_data["role"] != "worker":
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

    access_token = create_access_token(
        user_id=user_id,
        role="worker"
    )

    refresh_token = create_refresh_token(
        user_id=user_id,
        role="worker"
    )

    return {
        "status": True,
        "message": "LOGIN_SUCCESSFUL",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):

    user_id = payload["sub"]

    user = firestore_db.collection("workers").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "worker" or user_data["role"] != "worker":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    return {
        "status": True,
        "message": "USER_DATA_FETCHED",
        "user_data": {
            "user_id": user_data["user_id"],
            "role": user_data["role"],
            "user_name": user_data["user_name"],
            "phoneno": user_data.get("phoneno", "")
        }
    }

@router.post("/pickup/accept")
async def accept_pickup(
    pickup_acceptance_request_data: PickupAcceptanceRequest,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]
    pickup_id = pickup_acceptance_request_data.pickup_id

    user = firestore_db.collection(
        "workers"
    ).document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "worker" or user_data["role"] != "worker":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )
    
    assigned_reference = realtime_db.reference(
        f"pickups/assigned/{pickup_id}"
    )

    if assigned_reference.get() is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_NOT_ASSIGNED"
        )

    pickup_data_reference = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    )

    pickup_data = pickup_data_reference.get()

    if not pickup_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_DATA_NOT_FOUND"
        )

    household_id = pickup_data["household_id"]

    household_reference = realtime_db.reference(
        f"households/{household_id}"
    )

    accepted_time = datetime.now(timezone.utc).isoformat()

    def accept_assignment(current_data):

        if not current_data:
            return current_data

        if (
            current_data.get("pickup_id") != pickup_id
            or current_data.get("status") != "assigned"
        ):
            return current_data

        current_data["status"] = "accepted"
        current_data["worker_id"] = user_id
        current_data["accepted_at"] = accepted_time

        return current_data

    accepted_data = household_reference.transaction(
        accept_assignment
    )

    if (
        not accepted_data
        or accepted_data.get("pickup_id") != pickup_id
        or accepted_data.get("status") != "accepted"
        or accepted_data.get("worker_id") != user_id
    ):
        raise HTTPException(
            status_code= status.HTTP_409_CONFLICT,
            detail="PICKUP_ALREADY_ACCEPTED_OR_UNAVAILABLE"
        )

    try:

        realtime_db.reference().update({
            f"pickups/assigned/{pickup_id}": None,
            f"pickups/accepted/{pickup_id}": True,
            f"workers/{user_id}/accepted/{pickup_id}": True,
        })

    except Exception:

        def rollback_acceptance(current_data):

            if (
                current_data
                and current_data.get("pickup_id") == pickup_id
                and current_data.get("worker_id") == user_id
                and current_data.get("status") == "accepted"
            ):
                current_data["status"] = "assigned"
                current_data.pop("worker_id", None)
                current_data.pop("accepted_at", None)

            return current_data

        household_reference.transaction(rollback_acceptance)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_ACCEPTANCE_FAILED"
        )

    return {
        "status": True,
        "message": "Pickup has been accepted successfully",
        "pickup_id": pickup_id,
        "accepted_at": accepted_time
    }

@router.post("/refresh")
def get_access_token(
    payload: dict = Depends(get_refresh_token)
):

    user_id = payload["sub"]

    user = firestore_db.collection("workers").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NO_LONGER_EXISTS",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "worker" or user_data["role"] != "worker":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    access_token = create_access_token(user_id=user_id)

    return {
        "status": True,
        "message": "ACCESS_TOKEN_REFRESHED",
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 900
    }

@router.get("/pickup/accepted/data")
def get_accepted_pickups(
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    user = firestore_db.collection(
        "workers"
    ).document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "worker" or user_data["role"] != "worker":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    worker_pickups = realtime_db.reference(
        f"workers/{user_id}/accepted"
    ).get() or {}

    accepted_pickups = []

    for pickup_id in worker_pickups:

        pickup_data = realtime_db.reference(
            f"pickups/pickup_data/{pickup_id}"
        ).get()

        if not pickup_data:
            continue

        household_id = pickup_data.get("household_id")

        if not household_id:
            continue

        household_data = realtime_db.reference(
            f"households/{household_id}"
        ).get() or {}

        if (
            household_data.get("worker_id") != user_id
            or household_data.get("pickup_id") != pickup_id
            or household_data.get("status") not in ("accepted", "completed")
        ):
            continue

        household_profile = firestore_db.collection(
            "households"
        ).document(household_id).get()

        household_profile_data = (
            household_profile.to_dict() or {}
            if household_profile.exists
            else {}
        )

        accepted_pickups.append({
            "pickup_id": pickup_id,
            "household_id": household_id,
            "household_name": household_profile_data.get("user_name"),
            "worker_id": user_id,
            "status": household_data.get("status"),
            "accepted_at": household_data.get("accepted_at"),
            "pickup_data": {
                "time": pickup_data.get("time"),
                "coordinate": pickup_data.get("coordinate"),
                "qna": pickup_data.get("qna")
            }
        })

    return {
        "status": True,
        "message": "ACCEPTED_PICKUPS_RETRIEVED",
        "pickup_count": len(accepted_pickups),
        "pickups": accepted_pickups
    }

@router.websocket("/pickups")
async def pickup_stream(websocket: WebSocket):

    await websocket.accept()

    listener = None
    message_task = None
    pickup_task = None

    try:

        token = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=10
        )

        payload = validate_token(
            token=token,
            tokentype="access"
        )

        if not payload:
            await websocket.close(
                code=1008,
                reason="INVALID_OR_EXPIRED_ACCESS_TOKEN"
            )
            return

        user_id = payload["sub"]

        user = await asyncio.to_thread(
            firestore_db.collection("workers")
            .document(user_id).get
        )

        if not user.exists:
            await websocket.close(
                code=1008,
                reason="USER_NO_LONGER_EXISTS"
            )
            return

        user_data = user.to_dict() or {}

        if (
            payload.get("role") != "worker"
            or user_data.get("role") != "worker"
        ):
            await websocket.close(
                code=1008,
                reason="INSUFFICIENT_PERMISSIONS"
            )
            return

        assigned_reference = realtime_db.reference(
            "pickups/assigned"
        )

        queue = asyncio.Queue(maxsize=1)
        loop = asyncio.get_running_loop()

        def enqueue_update():

            if not queue.full():
                queue.put_nowait(True)

        def pickup_listener(event):

            loop.call_soon_threadsafe(enqueue_update)

        listener = assigned_reference.listen(pickup_listener)

        async def receive():

            while True:

                message = await websocket.receive_text()

                if message == "logout":
                    return

        async def pickup():

            while True:

                await queue.get()

                worker_assignments = await asyncio.to_thread(
                    assigned_reference.get
                ) or {}

                if not isinstance(worker_assignments, dict):
                    worker_assignments = {}

                pickup_list = []

                for pickup_id, assigned in worker_assignments.items():

                    if assigned is not True:
                        continue

                    pickup_data = await asyncio.to_thread(
                        realtime_db.reference(
                            f"pickups/pickup_data/{pickup_id}"
                        ).get
                    )

                    if not pickup_data:
                        continue

                    household_id = pickup_data.get("household_id")

                    if not household_id:
                        continue

                    household_data = await asyncio.to_thread(
                        realtime_db.reference(
                            f"households/{household_id}"
                        ).get
                    ) or {}

                    if household_data.get("status") != "assigned":
                        continue

                    household = await asyncio.to_thread(
                        firestore_db.collection("households")
                        .document(household_id).get
                    )

                    if not household.exists:
                        continue

                    household_profile = household.to_dict() or {}

                    pickup_list.append({
                        "pickupid": pickup_id,
                        "user_id": household_id,
                        "user_name": household_profile.get("user_name", ""),
                        "time": pickup_data.get("time"),
                        "coordinates": pickup_data.get("coordinate"),
                        "qna": pickup_data.get("qna")
                    })

                await websocket.send_json(pickup_list)

        message_task = asyncio.create_task(receive())
        pickup_task = asyncio.create_task(pickup())

        if not queue.full():
            queue.put_nowait(True)

        done, pending = await asyncio.wait(
            [message_task, pickup_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        await asyncio.gather(
            *pending,
            return_exceptions=True
        )

        for task in done:
            task.result()

    except asyncio.TimeoutError:

        await websocket.close(
            code=1008,
            reason="AUTHENTICATION_TIMEOUT"
        )

    except WebSocketDisconnect:
        pass

    finally:

        if message_task is not None and not message_task.done():
            message_task.cancel()

        if pickup_task is not None and not pickup_task.done():
            pickup_task.cancel()

        tasks = [
            task for task in (message_task, pickup_task)
            if task is not None
        ]

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True
            )

        if listener is not None:
            await asyncio.to_thread(listener.close)
