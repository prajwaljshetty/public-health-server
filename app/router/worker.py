
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from fastapi import Depends, HTTPException, status

from firebase_admin import db
from app.firebase import firestore_db, realtime_db
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models.worker import WorkerRegister, WorkerLogin, PickupAcceptanceRequest

import asyncio
from datetime import datetime, timezone

import uuid

from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_refresh_token,
    validate_token
)

from app.hasher import (
    hash_password,
    verify_password
)

router = APIRouter()


@router.post("/createaccount")
def create_account(worker: WorkerRegister):

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

    user_id = str(uuid.uuid4())
    password = hash_password(worker.password)

    firestore_db.collection("workers").document(user_id).set({
        "user_id": user_id,
        "worker_id": worker.worker_id,
        "user_name": worker.user_name,
        "phoneno": worker.phoneno,
        "password": password,
        "role": "worker"
    })

    access_token = create_access_token(user_id=user_id)
    refresh_token = create_refresh_token(user_id=user_id)

    return {
        "status": True,
        "message": "Account created successfully",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token
    }


@router.post("/login")
def login(user: WorkerLogin):

    users = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            user.worker_id
        )
    ).limit(1).stream()

    existing_user = next(users, None)

    if existing_user is None:
        return {
            "status": False,
            "message": "USER_NOT_FOUND",
            "user_id": None
        }

    user_data = existing_user.to_dict()

    if not verify_password(
        hashed_password=user_data["password"],
        password=user.password
    ):
        return {
            "status": False,
            "message": "INCORRECT_PASSWORD",
            "user_id": None
        }

    user_id = user_data["user_id"]

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

    user_id = payload["sub"]

    user = firestore_db.collection("workers").document(user_id).get()

    if not user.exists:
        return {
            "status": False,
            "message": "User does not exist",
            "user_data": None
        }

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

@router.post("/pickup/accept")
async def accept_pickup(
    pickup_acceptance_request_data: PickupAcceptanceRequest,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]
    pickup_id = pickup_acceptance_request_data.pickup_id

    worker_document = firestore_db.collection(
        "workers"
    ).document(user_id).get()

    if not worker_document.exists:
        raise HTTPException(
            status_code=404,
            detail="WORKER_NOT_FOUND"
        )

    assigned_reference = realtime_db.reference(
        f"pickups/assigned/{pickup_id}"
    )

    if assigned_reference.get() is not True:
        raise HTTPException(
            status_code=409,
            detail="PICKUP_NOT_ASSIGNED"
        )

    pickup_data_reference = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    )

    pickup_data = pickup_data_reference.get()

    if not pickup_data:
        raise HTTPException(
            status_code=404,
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
            status_code=409,
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
            status_code=500,
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
    request_data: dict = Depends(get_refresh_token)
):

    user_id = request_data["sub"]

    user = firestore_db.collection("workers").document(user_id).get()

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
        "expires_in": 900
    }

@router.get("/pickup/accepted/data")
async def get_accepted_pickups(
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    worker_document = firestore_db.collection(
        "workers"
    ).document(user_id).get()

    if not worker_document.exists:
        raise HTTPException(
            status_code=404,
            detail="WORKER_NOT_FOUND"
        )

    worker_pickups_reference = realtime_db.reference(
        f"workers/{user_id}/accepted"
    )

    worker_pickups_data = worker_pickups_reference.get() or {}

    accepted_pickups = []

    for pickup_id in worker_pickups_data:

        pickup_data = realtime_db.reference(
            f"pickups/pickup_data/{pickup_id}"
        ).get()

        if not pickup_data:
            continue

        household_id = pickup_data["household_id"]

        household_reference = realtime_db.reference(
            f"households/{household_id}"
        )

        household_data = household_reference.get() or {}

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
            household_profile.to_dict()
            if household_profile.exists
            else {}
        )

        accepted_pickups.append({
            "pickup_id": pickup_id,
            "household_id": household_id,
            "household_name": household_profile_data.get("user_name"),
            "worker_id": user_id,
            "accepted_at": household_data.get("accepted_at"),
            "pickup_data": {
                "time": pickup_data.get("time"),
                "coordinate": pickup_data.get("coordinate"),
                "qna": pickup_data.get("qna")
            }
        })

    return {
        "status": True,
        "message": "Accepted pickups retrieved successfully",
        "pickup_count": len(accepted_pickups),
        "pickups": accepted_pickups
    }

@router.websocket("/pickups")
async def pickup_stream(websocket: WebSocket):

    await websocket.accept()

    user_id = None
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
                reason="Invalid access token"
            )
            return

        user_id = payload["sub"]

        worker = await asyncio.to_thread(
            firestore_db.collection("workers").document(user_id).get
        )

        if not worker.exists:
            await websocket.close(
                code=1008,
                reason="Worker does not exist"
            )
            return

        assigned_reference = realtime_db.reference(
            "pickups/assigned"
        )

        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def pickup_listener(event):

            assigned_data = event.data

            if not isinstance(assigned_data, dict):
                assigned_data = {}

            asyncio.run_coroutine_threadsafe(
                queue.put(assigned_data),
                loop
            )

        listener = assigned_reference.listen(pickup_listener)

        initial_data = assigned_reference.get() or {}


        await queue.put(initial_data)

        async def receive():

            while True:

                message = await websocket.receive_text()

                if message == "logout":
                    print("Worker Logged out")
                    return

        async def pickup():

            while True:

                worker_assignments = await queue.get()

                if not isinstance(worker_assignments, dict):
                    worker_assignments = {}

                pickup_list = []

                for pickup_id, assigned in worker_assignments.items():

                    if assigned is not True:
                        continue

                    pickup_data = realtime_db.reference(
                        f"pickups/pickup_data/{pickup_id}"
                    ).get()

                    if not pickup_data:
                        continue

                    household_id = pickup_data["household_id"]

                    household_data = realtime_db.reference(
                        f"households/{household_id}"
                    ).get() or {}

                    if household_data.get("status") != "assigned":
                        continue

                    household = await asyncio.to_thread(
                        firestore_db.collection("households").document(
                            household_id
                        ).get
                    )

                    if not household.exists:
                        continue

                    household_profile = household.to_dict()

                    pickup_list.append({
                        "pickupid": pickup_id,
                        "user_id": household_id,
                        "user_name": household_profile["user_name"],
                        "time": pickup_data.get("time"),
                        "coordinates": pickup_data.get("coordinate"),
                        "qna": pickup_data.get("qna")
                    })

                await websocket.send_json(pickup_list)

        message_task = asyncio.create_task(receive())
        pickup_task = asyncio.create_task(pickup())
        
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
            reason="Authentication timeout"
        )

    except WebSocketDisconnect:
        pass

    finally:

        if message_task is not None and not message_task.done():
            message_task.cancel()

        if pickup_task is not None and not pickup_task.done():
            pickup_task.cancel()

        if listener is not None:
            await asyncio.to_thread(listener.close)
