# OS
import asyncio
import os
import uuid

# HTTP
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

# Date Time :
from datetime import datetime, timezone

# Firebase
from app.firebase import firestore_db, realtime_db

# Filter
from google.cloud.firestore_v1.base_query import FieldFilter

# Models
from app.models.admin import AdminLogin, AdminRegister, RewardPolicy
from app.models.worker import WorkerRegister, WorkerUpdate

# Authentication
from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_refresh_token,
    validate_token,
)

# Password
from app.hasher import hash_password, verify_password

router = APIRouter()

@router.post("/create")
def create_admin(admin_data: AdminRegister):

    email = admin_data.email.strip().lower()

    if not email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="EMAIL_REQUIRED"
        )

    admins = firestore_db.collection("admins").where(
        filter=FieldFilter("email", "==", email)
    ).limit(1).stream()

    if next(admins, None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ADMIN_ALREADY_EXISTS"
        )

    user_id = str(uuid.uuid4())

    password = hash_password(admin_data.password)

    firestore_db.collection("admins").document(user_id).set({
        "user_id": user_id,
        "email": email,
        "password": password,
        "reward_policy": admin_data.reward_policy.model_dump(),
        "role": "admin"
    })

    access_token = create_access_token(
        user_id=user_id,
        role="admin"
    )

    refresh_token = create_refresh_token(
        user_id=user_id,
        role="admin"
    )

    return {
        "status": True,
        "message": "ADMIN_ACCOUNT_CREATED",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/login")
def login(login_data: AdminLogin):

    admin = firestore_db.collection("admins").where(
        filter=FieldFilter(
            "email",
            "==",
            login_data.email.strip().lower()
        )
    ).limit(1).stream()

    existing_admin = next(admin, None)

    if not existing_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NOT_FOUND",
            headers={"WWW-Authenticate": "Bearer"}
        )

    admin_data = existing_admin.to_dict() or {}

    if admin_data.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    if not verify_password(
        hashed_password=admin_data.get("password", ""),
        password=login_data.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INCORRECT_PASSWORD",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_id = existing_admin.id

    access_token = create_access_token(
        user_id=user_id,
        role="admin"
    )

    refresh_token = create_refresh_token(
        user_id=user_id,
        role="admin"
    )

    return {
        "status": True,
        "message": "LOGIN_SUCCESSFUL",
        "user_id": user_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/refresh")
def get_access_token(
    payload: dict = Depends(get_refresh_token)
):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="USER_NOT_FOUND",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "admin" or user_data["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    return {
        "status": True,
        "message": "ACCESS_TOKEN_REFRESHED",
        "access_token": create_access_token(
            user_id=user_id,
            role="admin"
        ),
        "token_type": "bearer",
        "expires_in": 900
    }

@router.get("/data")
def get_data(payload: dict = Depends(get_current_user)):

    user_id = payload["sub"]

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if payload["role"] != "admin" or user_data["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    return {
        "status": True,
        "message": "USER_DATA_FETCHED",
        "user_data": {
            "user_id": user_data["user_id"],
            "email": user_data["email"],
            "role": user_data["role"],
            "reward_policy": user_data.get("reward_policy", {})
        }
    }


# Worker Control :
@router.post("/workers/create")
def create_account(
    worker: WorkerRegister,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists or admin.to_dict()["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    workers = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker.worker_id.strip().upper()
        )
    ).limit(1).stream()

    if next(workers, None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WORKER_ALREADY_EXISTS"
        )

    worker_id = str(uuid.uuid4())

    password = hash_password(worker.password)

    firestore_db.collection("workers").document(worker_id).set({
        "user_id": worker_id,
        "worker_id": worker.worker_id.strip().upper(),
        "user_name": worker.user_name.strip(),
        "phoneno": worker.phoneno.strip(),
        "password": password,
        "role": "worker",
        "admin_id": user_id
    })

    return {
        "status": True,
        "message": "WORKER_ACCOUNT_CREATED",
        "user_id": worker_id,
        "worker_id": worker.worker_id.strip().upper()
    }

@router.get("/workers")
def get_workers(
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists or admin.to_dict()["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    workers = []

    workers = firestore_db.collection("workers").where(
        filter=FieldFilter("admin_id", "==", user_id)
    ).stream()

    for document in workers:
        worker_data = document.to_dict() or {}

        workers.append({
            "worker_id": worker_data.get("worker_id", ""),
            "name": worker_data.get("user_name", ""),
            "phoneno": worker_data.get("phoneno", "")
        })

    workers.sort(key=lambda item: item["worker_id"])

    return {
        "status": True,
        "message": "WORKERS_FETCHED",
        "workers": workers
    }

@router.get("/workers/{worker_id}")
def get_worker(
    worker_id: str,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists or admin.to_dict()["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    workers = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_id.strip().upper()
        )).where(
        filter=FieldFilter(
            "admin_id",
            "==",
            user_id
        )
    ).limit(1).stream()

    existing_worker = next(workers, None)

    if not existing_worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND"
        )

    worker_data = existing_worker.to_dict() or {}

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
    changes: WorkerUpdate,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists or admin.to_dict()["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    workers = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_id.strip().upper()
        )).where(
        filter=FieldFilter(
            "admin_id",
            "==",
            user_id
        )
    ).limit(1).stream()

    existing_worker = next(workers, None)

    if not existing_worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND"
        )

    updates = {}

    if changes.name is not None:

        name = changes.name.strip()

        if not name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="INVALID_NAME"
            )

        updates["user_name"] = name

    if changes.password:
        updates["password"] = hash_password(changes.password)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NO_UPDATES_PROVIDED"
        )

    existing_worker.reference.update(updates)

    worker_data = existing_worker.to_dict() or {}

    return {
        "status": True,
        "message": "WORKER_UPDATED",
        "worker": {
            "worker_id": worker_data.get("worker_id", ""),
            "name": updates.get(
                "user_name",
                worker_data.get("user_name", "")
            ),
            "phoneno": worker_data.get("phoneno", "")
        }
    }

@router.delete("/workers/{worker_id}")
def delete_worker(
    worker_id: str,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists or admin.to_dict()["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    workers = firestore_db.collection("workers").where(
        filter=FieldFilter(
            "worker_id",
            "==",
            worker_id.strip().upper()
        )).where(
        filter=FieldFilter(
            "admin_id",
            "==",
            user_id
        )
    ).limit(1).stream()

    existing_worker = next(workers, None)

    if not existing_worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND"
        )

    existing_worker.reference.delete()

    return {
        "status": True,
        "message": "WORKER_DELETED"
    }


# Reward Policy :
@router.patch("/reward-policy")
def update_reward_policy(
    reward_policy: RewardPolicy,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin = firestore_db.collection("admins").document(user_id).get()

    if not admin.exists or admin.to_dict()["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    reward_policy_data = reward_policy.model_dump()

    firestore_db.collection("admins").document(user_id).update({
        "reward_policy": reward_policy_data
    })

    return {
        "status": True,
        "message": "REWARD_POLICY_UPDATED",
        "reward_policy": reward_policy_data
    }


# Pickups :
@router.post("/pickup/assign")
def assign_pickup(
    pickup_id: str,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    if payload["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    user = firestore_db.collection("admins").document(user_id).get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if user_data["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    pickup_ref = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    )

    pickup_data = pickup_ref.get()

    if not isinstance(pickup_data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_NOT_FOUND"
        )

    household_id = pickup_data.get("household_id")

    if not household_id:
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

    household_ref = realtime_db.reference(
        f"households/{household_id}"
    )

    household_data = household_ref.get()

    if not isinstance(household_data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND"
        )

    if (
        household_data.get("status") != "requested"
        or household_data.get("pickup_id") != pickup_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HOUSEHOLD_PICKUP_ALREADY_ASSIGNED_OR_UNAVAILABLE"
        )

    transitioned = False

    def assign_household(current_data):

        nonlocal transitioned

        transitioned = False

        if (
            not isinstance(current_data, dict)
            or current_data.get("status") != "requested"
            or current_data.get("pickup_id") != pickup_id
        ):
            return current_data

        current_data["status"] = "assigned"

        transitioned = True

        return current_data

    assigned_household = household_ref.transaction(
        assign_household
    )

    if (
        not transitioned
        or not isinstance(assigned_household, dict)
        or assigned_household.get("status") != "assigned"
        or assigned_household.get("pickup_id") != pickup_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HOUSEHOLD_PICKUP_ALREADY_ASSIGNED_OR_UNAVAILABLE"
        )

    assigned_at = datetime.now(timezone.utc).isoformat()

    audit_data = {
        "pickup_id": pickup_id,
        "household_id": household_id,
        "assigned_by": user_id,
        "assigned_at": assigned_at
    }

    try:

        realtime_db.reference().update({
            f"pickups/requested/{pickup_id}": None,
            f"pickups/assigned/{pickup_id}": True,
            f"audit/assigned/{pickup_id}": audit_data
        })

    except Exception as error:

        def rollback_assignment(current_data):

            if (
                isinstance(current_data, dict)
                and current_data.get("status") == "assigned"
                and current_data.get("pickup_id") == pickup_id
            ):
                current_data["status"] = "requested"

            return current_data

        household_ref.transaction(rollback_assignment)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_ASSIGNMENT_FAILED"
        ) from error

    return {
        "status": True,
        "message": "PICKUP_ASSIGNED_SUCCESSFULLY",
        "pickup_id": pickup_id,
        "household_id": household_id
    }

@router.websocket("/pickups")
async def pickup_stream(websocket: WebSocket):

    await websocket.accept()

    listener = None
    receive_task = None
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

        if not payload or payload.get("role") != "admin":
            await websocket.close(
                code=1008,
                reason="INVALID_ADMIN_TOKEN"
            )
            return

        admin = await asyncio.to_thread(
            firestore_db.collection("admins")
            .document(payload["sub"]).get
        )

        if (
            not admin.exists
            or (admin.to_dict() or {}).get("role") != "admin"
        ):
            await websocket.close(
                code=1008,
                reason="ADMIN_NO_LONGER_EXISTS"
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

        def pickup_listener(_event):

            loop.call_soon_threadsafe(enqueue_update)

        listener = requested_reference.listen(pickup_listener)

        async def receive():

            while True:

                message = await websocket.receive_text()

                if message == "logout":
                    return

        async def send_pickups():

            while True:

                await queue.get()

                requested = await asyncio.to_thread(
                    requested_reference.get
                ) or {}

                pickup_data = await asyncio.to_thread(
                    realtime_db.reference("pickups/pickup_data").get
                ) or {}

                pickup_list = []

                if isinstance(requested, dict):

                    for pickup_id, is_requested in requested.items():

                        if is_requested is not True:
                            continue

                        pickup = pickup_data.get(pickup_id)

                        if not isinstance(pickup, dict):
                            continue

                        household_id = pickup.get("household_id")

                        if not household_id:
                            continue

                        household_state = await asyncio.to_thread(
                            realtime_db.reference(
                                f"households/{household_id}"
                            ).get
                        ) or {}

                        if (
                            household_state.get("status") != "requested"
                            or household_state.get("pickup_id") != pickup_id
                        ):
                            continue

                        household = await asyncio.to_thread(
                            firestore_db.collection("households")
                            .document(household_id).get
                        )

                        household_profile = (
                            household.to_dict() or {}
                            if household.exists
                            else {}
                        )

                        pickup_list.append({
                            "pickupid": pickup_id,
                            "user_id": household_id,
                            "user_name": household_profile.get("user_name", ""),
                            "phoneno": household_profile.get("phoneno", ""),
                            "time": pickup.get("time"),
                            "coordinates": pickup.get("coordinates"),
                            "qna": pickup.get("qna", []),
                            "status": "requested"
                        })

                pickup_list.sort(
                    key=lambda item: item.get("time") or "",
                    reverse=True
                )

                await websocket.send_json(pickup_list)

        receive_task = asyncio.create_task(receive())
        pickup_task = asyncio.create_task(send_pickups())

        if not queue.full():
            queue.put_nowait(True)

        done, pending = await asyncio.wait(
            [receive_task, pickup_task],
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

        for task in (receive_task, pickup_task):

            if task is not None and not task.done():
                task.cancel()

        tasks = [
            task
            for task in (receive_task, pickup_task)
            if task is not None
        ]

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True
            )

        if listener is not None:
            await asyncio.to_thread(listener.close)
