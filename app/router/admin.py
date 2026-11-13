import asyncio
import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from google.cloud.firestore_v1.base_query import FieldFilter

from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_refresh_token,
    validate_token,
)
from app.firebase import firestore_db, realtime_db
from app.hasher import hash_password, verify_password
from app.models.admin import AdminLogin
from app.models.worker import WorkerRegister, WorkerUpdate


router = APIRouter()


def _admin_document(payload: dict):
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS",
        )

    document = firestore_db.collection("admins").document(payload["sub"]).get()
    data = document.to_dict() or {} if document.exists else {}
    if not document.exists or data.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ADMIN_NO_LONGER_EXISTS",
        )
    return document


def _find_worker(worker_id: str):
    workers = (
        firestore_db.collection("workers")
        .where(filter=FieldFilter("worker_id", "==", worker_id.strip().upper()))
        .limit(1)
        .stream()
    )
    return next(workers, None)


def _worker_payload(document) -> dict:
    data = document.to_dict() or {}
    return {
        "worker_id": data.get("worker_id", ""),
        "name": data.get("user_name", ""),
        "phoneno": data.get("phoneno", ""),
    }


def _requested_pickups() -> list[dict]:
    requested = realtime_db.reference("pickups/requested").get() or {}
    pickup_data = realtime_db.reference("pickups/pickup_data").get() or {}
    results = []

    if not isinstance(requested, dict):
        return results

    for pickup_id, is_requested in requested.items():
        if is_requested is not True:
            continue

        pickup = pickup_data.get(pickup_id)
        if not isinstance(pickup, dict):
            continue

        household_id = pickup.get("household_id")
        household_profile = {}
        household_state = {}
        if household_id:
            profile_document = (
                firestore_db.collection("households").document(household_id).get()
            )
            if profile_document.exists:
                household_profile = profile_document.to_dict() or {}
            household_state = (
                realtime_db.reference(f"households/{household_id}").get() or {}
            )

        if household_state.get("status") != "requested":
            continue

        results.append({
            "pickupid": pickup_id,
            "user_id": household_id,
            "user_name": household_profile.get("user_name", ""),
            "phoneno": household_profile.get("phoneno", ""),
            "time": pickup.get("time"),
            "coordinates": pickup.get("coordinate"),
            "qna": pickup.get("qna", []),
            "status": "requested",
        })

    results.sort(key=lambda item: item.get("time") or "", reverse=True)
    return results


@router.post("/login")
def login(credentials: AdminLogin):
    email = credentials.email.strip().lower()
    admins = (
        firestore_db.collection("admins")
        .where(filter=FieldFilter("email", "==", email))
        .limit(1)
        .stream()
    )
    admin = next(admins, None)

    if admin is None:
        bootstrap_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        bootstrap_password = os.getenv("ADMIN_PASSWORD", "")
        if not bootstrap_email or email != bootstrap_email or credentials.password != bootstrap_password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="INVALID_ADMIN_CREDENTIALS",
            )

        admin_id = str(uuid.uuid4())
        admin_data = {
            "user_id": admin_id,
            "email": email,
            "password": hash_password(credentials.password),
            "role": "admin",
        }
        firestore_db.collection("admins").document(admin_id).set(admin_data)
    else:
        admin_id = admin.id
        admin_data = admin.to_dict() or {}
        stored_password = admin_data.get("password")
        if (
            admin_data.get("role") != "admin"
            or not isinstance(stored_password, str)
            or not stored_password.startswith("$argon2")
            or not verify_password(
                password=credentials.password,
                hashed_password=stored_password,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="INVALID_ADMIN_CREDENTIALS",
            )

    return {
        "status": True,
        "message": "ADMIN_LOGIN_SUCCESSFUL",
        "user_id": admin_id,
        "email": email,
        "access_token": create_access_token(admin_id, role="admin"),
        "refresh_token": create_refresh_token(admin_id, role="admin"),
        "token_type": "bearer",
    }


@router.post("/refresh")
def refresh_access_token(payload: dict = Depends(get_refresh_token)):
    _admin_document(payload)
    return {
        "status": True,
        "message": "ACCESS_TOKEN_REFRESHED",
        "access_token": create_access_token(payload["sub"], role="admin"),
        "token_type": "bearer",
        "expires_in": 900,
    }


@router.post("/createaccount", status_code=status.HTTP_201_CREATED)
def create_account(
    worker: WorkerRegister,
    payload: dict = Depends(get_current_user),
):
    _admin_document(payload)
    worker_code = worker.worker_id.strip().upper()
    if not worker_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WORKER_ID_REQUIRED",
        )
    if _find_worker(worker_code):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WORKER_ALREADY_EXISTS",
        )

    user_id = str(uuid.uuid4())
    firestore_db.collection("workers").document(user_id).set({
        "user_id": user_id,
        "worker_id": worker_code,
        "user_name": worker.user_name.strip(),
        "phoneno": worker.phoneno.strip(),
        "password": hash_password(worker.password),
        "role": "worker",
    })
    return {
        "status": True,
        "message": "WORKER_ACCOUNT_CREATED",
        "worker_id": worker_code,
    }


@router.get("/workers")
def get_workers(payload: dict = Depends(get_current_user)):
    _admin_document(payload)
    workers = [
        _worker_payload(document)
        for document in firestore_db.collection("workers").stream()
    ]
    workers.sort(key=lambda item: item["worker_id"])
    return {
        "status": True,
        "message": "WORKERS_FETCHED",
        "workers": workers,
    }


@router.get("/workers/{worker_id}")
def get_worker(worker_id: str, payload: dict = Depends(get_current_user)):
    _admin_document(payload)
    worker = _find_worker(worker_id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND",
        )
    return {
        "status": True,
        "message": "WORKER_FETCHED",
        "worker": _worker_payload(worker),
    }


@router.patch("/workers/{worker_id}")
def update_worker(
    worker_id: str,
    changes: WorkerUpdate,
    payload: dict = Depends(get_current_user),
):
    _admin_document(payload)
    worker = _find_worker(worker_id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND",
        )

    updates = {}
    if changes.name is not None:
        name = changes.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="INVALID_NAME",
            )
        updates["user_name"] = name
    if changes.password:
        updates["password"] = hash_password(changes.password)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NO_UPDATES_PROVIDED",
        )

    worker.reference.update(updates)
    return {
        "status": True,
        "message": "WORKER_UPDATED",
        "worker": {
            **_worker_payload(worker),
            **({"name": updates["user_name"]} if "user_name" in updates else {}),
        },
    }


@router.delete("/workers/{worker_id}")
def delete_worker(worker_id: str, payload: dict = Depends(get_current_user)):
    _admin_document(payload)
    worker = _find_worker(worker_id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND",
        )
    worker.reference.delete()
    return {"status": True, "message": "WORKER_DELETED"}


@router.get("/pickups/requests")
def get_pickup_requests(payload: dict = Depends(get_current_user)):
    _admin_document(payload)
    return {
        "status": True,
        "message": "PICKUP_REQUESTS_FETCHED",
        "pickup_requests": _requested_pickups(),
    }


@router.post("/pickup/assign")
def assign_pickup(
    pickup_id: str,
    payload: dict = Depends(get_current_user),
):
    _admin_document(payload)
    pickup_data = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    ).get()
    if not isinstance(pickup_data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_NOT_FOUND",
        )
    if realtime_db.reference(f"pickups/requested/{pickup_id}").get() is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_NOT_AVAILABLE_FOR_ASSIGNMENT",
        )

    household_id = pickup_data.get("household_id")
    if not household_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HOUSEHOLD_ID_MISSING",
        )
    household_reference = realtime_db.reference(f"households/{household_id}")

    def claim_household(current_data):
        if (
            not isinstance(current_data, dict)
            or current_data.get("pickup_id") != pickup_id
            or current_data.get("status") != "requested"
        ):
            return current_data
        return {**current_data, "status": "assigned"}

    claimed_household = household_reference.transaction(claim_household)
    if (
        not isinstance(claimed_household, dict)
        or claimed_household.get("pickup_id") != pickup_id
        or claimed_household.get("status") != "assigned"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="HOUSEHOLD_PICKUP_ALREADY_ASSIGNED_OR_UNAVAILABLE",
        )

    try:
        realtime_db.reference().update({
            f"pickups/requested/{pickup_id}": None,
            f"pickups/assigned/{pickup_id}": True,
        })
    except Exception as error:
        def rollback(current_data):
            if (
                isinstance(current_data, dict)
                and current_data.get("pickup_id") == pickup_id
                and current_data.get("status") == "assigned"
                and not current_data.get("worker_id")
            ):
                return {**current_data, "status": "requested"}
            return current_data

        household_reference.transaction(rollback)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_ASSIGNMENT_FAILED",
        ) from error

    return {
        "status": True,
        "message": "PICKUP_ASSIGNED",
        "pickup_id": pickup_id,
        "household_id": household_id,
    }


@router.websocket("/pickups")
async def pickup_stream(websocket: WebSocket):
    await websocket.accept()
    listener = None
    receive_task = None
    pickup_task = None

    try:
        token = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        payload = validate_token(token=token, tokentype="access")
        if not payload or payload.get("role") != "admin":
            await websocket.close(code=1008, reason="INVALID_ADMIN_TOKEN")
            return

        admin = await asyncio.to_thread(
            firestore_db.collection("admins").document(payload["sub"]).get
        )
        if not admin.exists or (admin.to_dict() or {}).get("role") != "admin":
            await websocket.close(code=1008, reason="ADMIN_NO_LONGER_EXISTS")
            return

        requested_reference = realtime_db.reference("pickups/requested")
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
                if await websocket.receive_text() == "logout":
                    return

        async def send_pickups():
            while True:
                await queue.get()
                pickups = await asyncio.to_thread(_requested_pickups)
                await websocket.send_json(pickups)

        if not queue.full():
            queue.put_nowait(True)
        receive_task = asyncio.create_task(receive())
        pickup_task = asyncio.create_task(send_pickups())
        done, pending = await asyncio.wait(
            [receive_task, pickup_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="AUTHENTICATION_TIMEOUT")
    except WebSocketDisconnect:
        pass
    finally:
        for task in (receive_task, pickup_task):
            if task is not None and not task.done():
                task.cancel()
        tasks = [task for task in (receive_task, pickup_task) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if listener is not None:
            await asyncio.to_thread(listener.close)
