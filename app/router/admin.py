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
    WorkerRegister,
    WorkerUpdate,
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

@router.post("/createaccount")
def create_account(
    worker_data: WorkerRegister,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "admin"
        or user_data.get("role") != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    worker_code = worker_data.worker_id.strip().upper()

    existing_worker = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_code
        )
    ).limit(1).stream()

    if next(existing_worker, None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WORKER_ALREADY_EXISTS"
        )

    worker_id = str(uuid.uuid4())
    password = hash_password(worker_data.password)

    firestore_db.collection("workers").document(worker_id).set({
        "user_id": worker_id,
        "worker_id": worker_code,
        "user_name": worker_data.user_name,
        "phoneno": worker_data.phoneno,
        "password": password,
        "role": "worker"
    })

    return {
        "status": True,
        "message": "WORKER_ACCOUNT_CREATED",
        "worker_id": worker_code ,
        "password": worker_data.password,
    }

@router.get("/workers")
def get_workers(payload: dict = Depends(get_current_user)):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "admin"
        or user_data.get("role") != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    workers = []

    for document in firestore_db.collection("workers").stream():

        data = document.to_dict() or {}

        workers.append({
            "worker_id": data.get("worker_id", ""),
            "name": data.get("user_name", ""),
            "phoneno": data.get("phoneno", "")
        })

    workers.sort(key=lambda item: item["worker_id"])

    return {
        "status": True,
        "message": "Workers fetched successfully",
        "workers": workers
    }

@router.get("/workers/{worker_id}")
def get_worker(
    worker_id: str,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ADMIN_NOT_FOUND"
        )

    admin_data = admin.to_dict() or {}

    if (
        payload.get("role") != "admin"
        or admin_data.get("role") != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    worker = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_id.strip().upper()
        )
    ).limit(1).stream()

    worker = next(worker, None)

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND"
        )

    worker_data = worker.to_dict() or {}

    return {
        "status": True,
        "message": "WORKER_FETCHED",
        "worker": {
            "worker_id": worker_data.get("worker_id", ""),
            "name": worker_data.get("user_name", ""),
            "phoneno": worker_data.get("phoneno", "")
        }
    }

@router.patch("/workers/{worker_id}")
def update_worker(
    worker_id: str,
    worker_update_data: WorkerUpdate,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "admin"
        or user_data.get("role") != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    worker = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_id.strip().upper()
        )
    ).limit(1).stream()

    worker = next(worker, None)

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND"
        )

    updates = {}

    if worker_update_data.name is not None:

        name = worker_update_data.name.strip()

        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="INVALID_NAME"
            )

        updates["user_name"] = name

    if worker_update_data.password:
        updates["password"] = hash_password(
            worker_update_data.password
        )

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NO_UPDATES_PROVIDED"
        )

    worker.reference.update(updates)

    return {
        "status": True,
        "message": "WORKER_UPDATED",
        "worker": {
            "worker_id": worker_id.strip().upper(),
            **({"name": updates["user_name"]} if "user_name" in updates else {})
        }
    }

@router.delete("/workers/{worker_id}")
def delete_worker(
    worker_id: str,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "admin"
        or user_data.get("role") != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    worker = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_id.strip().upper()
        )
    ).limit(1).stream()

    worker = next(worker, None)

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND"
        )

    worker.reference.delete()

    return {
        "status": True,
        "message": "WORKER_DELETED"
    }

@router.post("/pickup/assign")
def assign_pickup(
    pickup_id: str,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "admin"
        or user_data.get("role") != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    pickup_ref = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    )

    pickup_data = pickup_ref.get()

    if not pickup_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_NOT_FOUND"
        )

    requested_ref = realtime_db.reference(
        f"pickups/requested/{pickup_id}"
    )

    if requested_ref.get() is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_NOT_AVAILABLE_FOR_ASSIGNMENT"
        )

    household_id = pickup_data.get("household_id")

    if not household_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HOUSEHOLD_ID_MISSING"
        )

    household_ref = realtime_db.reference(
        f"households/{household_id}"
    )

    household_data = household_ref.get()

    if not household_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND"
        )

    def assign_household(current_data):
        if (
            not current_data
            or current_data.get("pickup_id") != pickup_id
            or current_data.get("status") != "requested"
        ):
            return current_data

        current_data["status"] = "assigned"

        return current_data

    def rollback_assignment(current_data):
        if (
            current_data
            and current_data.get("pickup_id") == pickup_id
            and current_data.get("status") == "assigned"
        ):
            current_data["status"] = "requested"

            return current_data
 
    assigned_household = household_ref.transaction(assign_household)

    if (
        not assigned_household
        or assigned_household.get("pickup_id") != pickup_id
        or assigned_household.get("status") != "assigned"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HOUSEHOLD_PICKUP_ALREADY_ASSIGNED_OR_UNAVAILABLE"
        )

    try:
        realtime_db.reference().update({
            f"pickups/requested/{pickup_id}": None,
            f"pickups/assigned/{pickup_id}": True
        })

    except Exception:
        household_ref.transaction(rollback_assignment)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_ASSIGNMENT_FAILED"
        )

    return {
        "status": True,
        "message": "PICKUP_ASSIGNED",
        "pickup_id": pickup_id,
        "household_id": household_id
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
            firestore_db.collection("admins")
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
            payload.get("role") != "admin"
            or user_data.get("role") != "admin"
        ):
            await websocket.close(
                code=1008,
                reason="INSUFFICIENT_PERMISSIONS"
            )
            return

        requested_reference = realtime_db.reference(
            "pickups/requested"
        )

        queue = asyncio.Queue(maxsize=1)
        loop = asyncio.get_running_loop()

        def enqueue_update():
            if not queue.full():
                queue.put_nowait(True)

        def pickup_listener(event):
            loop.call_soon_threadsafe(enqueue_update)

        listener = requested_reference.listen(pickup_listener)

        async def receive():

            while True:

                message = await websocket.receive_text()

                if message == "logout":
                    print("Admin Logged out")
                    return

        async def pickup():

            while True:

                await queue.get()

                requested_data = await asyncio.to_thread(
                    requested_reference.get
                ) or {}

                if not isinstance(requested_data, dict):
                    requested_data = {}

                pickup_list = []

                for pickup_id, requested in requested_data.items():

                    if requested is not True:
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

                    if household_data.get("status") != "requested":
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