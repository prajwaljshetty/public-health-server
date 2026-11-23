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
    PickupCollectionConfirmation
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
    verify_password,
)

# Point Calculation :
from app.points import calculate_point

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

    return {
        "status": True,
        "message": "ACCESS_TOKEN_REFRESHED",
        "access_token": create_access_token(
            user_id=user_id,
            role="worker"
        ),
        "token_type": "bearer",
        "expires_in": 900
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
            "worker_id": user_data["worker_id"],
            "role": user_data["role"],
            "user_name": user_data["user_name"],
            "phoneno": user_data.get("phoneno", "")
        }
    }


# Pickup :
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

    if (
        payload.get("role") != "worker"
        or user_data.get("role") != "worker"
    ):
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

    household_id = pickup_data.get("household_id")

    if not household_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HOUSEHOLD_ID_MISSING"
        )

    household_reference = realtime_db.reference(
        f"households/{household_id}"
    )

    accepted_at = datetime.now(timezone.utc).isoformat()

    transitioned = False

    def accept_assignment(current_data):

        nonlocal transitioned

        transitioned = False

        if (
            not current_data
            or current_data.get("pickup_id") != pickup_id
            or current_data.get("status") != "assigned"
        ):
            return current_data

        current_data["status"] = "accepted"

        transitioned = True

        return current_data

    accepted_data = household_reference.transaction(
        accept_assignment
    )

    if (
        not transitioned
        or not accepted_data
        or accepted_data.get("pickup_id") != pickup_id
        or accepted_data.get("status") != "accepted"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_ALREADY_ACCEPTED_OR_UNAVAILABLE"
        )

    audit_data = {
        "household_id": household_id,
        "accepted_by": user_id,
        "pickup_id": pickup_id,
        "accepted_at": accepted_at,
    }

    try:

        realtime_db.reference().update({
            f"pickups/assigned/{pickup_id}": None,
            f"pickups/accepted/{pickup_id}": True,
            f"workers/{user_id}/accepted/{pickup_id}": True,
            f"audit/accepted/{pickup_id}": audit_data,
        })

    except Exception:

        def rollback_acceptance(current_data):

            if (
                current_data
                and current_data.get("pickup_id") == pickup_id
                and current_data.get("status") == "accepted"
            ):
                current_data["status"] = "assigned"

            return current_data

        household_reference.transaction(
            rollback_acceptance
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PICKUP_ACCEPTANCE_FAILED"
        )

    return {
        "status": True,
        "message": "Pickup has been accepted successfully",
        "pickup_id": pickup_id,
        "accepted_at": accepted_at
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

    if (
        payload.get("role") != "worker"
        or user_data.get("role") != "worker"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    worker_pickups = realtime_db.reference(
        f"workers/{user_id}/accepted"
    ).get() or {}

    if not isinstance(worker_pickups, dict):
        worker_pickups = {}

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
            household_data.get("pickup_id") != pickup_id
            or household_data.get("status") != "accepted"
        ):
            continue

        accepted_audit = realtime_db.reference(
            f"audit/accepted/{pickup_id}"
        ).get()

        if (
            not accepted_audit
            or accepted_audit.get("accepted_by") != user_id
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
            "accepted_at": accepted_audit.get("accepted_at"),
            "pickup_data": {
                "time": pickup_data.get("time"),
                "coordinates": pickup_data.get("coordinates"),
                "qna": pickup_data.get("qna")
            }
        })

    return {
        "status": True,
        "message": "ACCEPTED_PICKUPS_RETRIEVED",
        "pickup_count": len(accepted_pickups),
        "pickups": accepted_pickups
    }

@router.post("/pickup/confirm-collection")
async def confirm_collection(
    collection_confirmation_data: PickupCollectionConfirmation,
    payload: dict = Depends(get_current_user)
):

    user_id = payload["sub"]

    user_reference = firestore_db.collection("workers").document(user_id)
    user = user_reference.get()

    if not user.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="USER_NOT_FOUND"
        )

    user_data = user.to_dict() or {}

    if (
        payload.get("role") != "worker"
        or user_data.get("role") != "worker"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    admin_id = user_data.get("admin_id")

    if not admin_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ADMIN_NOT_FOUND"
        )

    admin = firestore_db.collection("admins").document(admin_id).get()

    if not admin.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ADMIN_NOT_FOUND"
        )

    admin_data = admin.to_dict() or {}

    if admin_data.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="INSUFFICIENT_PERMISSIONS"
        )

    pickup_id = collection_confirmation_data.pickup_id
    code = collection_confirmation_data.code

    pickup_data_reference = realtime_db.reference(
        f"pickups/pickup_data/{pickup_id}"
    )

    pickup_data = pickup_data_reference.get()

    if not isinstance(pickup_data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_DATA_NOT_FOUND"
        )

    household_id = pickup_data.get("household_id")

    if not household_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INVALID_PICKUP_DATA"
        )

    household_reference = realtime_db.reference(
        f"households/{household_id}"
    )

    household_data = household_reference.get()

    if not isinstance(household_data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HOUSEHOLD_NOT_FOUND"
        )

    pending_data = household_data.get("collection_pending")

    is_retry = (
        household_data.get("status") == "collection_pending_sync"
        and isinstance(pending_data, dict)
        and pending_data.get("pickup_id") == pickup_id
        and pending_data.get("household_id") == household_id
        and pending_data.get("collected_by") == user_id
    )

    if is_retry:

        points = pending_data.get("point_rewarded")
        collected_at = pending_data.get("collected_at")

        if (
            not isinstance(points, int)
            or isinstance(points, bool)
            or points < 0
            or not isinstance(collected_at, str)
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INVALID_PENDING_COLLECTION"
            )

    else:

        if household_data.get("status") == "collection_pending_sync":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="COLLECTION_ALREADY_PENDING"
            )

        if (
            household_data.get("status") != "accepted"
            or household_data.get("pickup_id") != pickup_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PICKUP_NOT_AVAILABLE_FOR_COLLECTION"
            )

        accepted_reference = realtime_db.reference(
            f"pickups/accepted/{pickup_id}"
        )

        if accepted_reference.get() is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PICKUP_NOT_ACCEPTED"
            )

        worker_accepted_reference = realtime_db.reference(
            f"workers/{user_id}/accepted/{pickup_id}"
        )

        if worker_accepted_reference.get() is not True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="PICKUP_NOT_ASSIGNED_TO_WORKER"
            )

        if not code.isdigit() or len(code) != 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="INVALID_PICKUP_CODE"
            )

        stored_code = household_data.get("code", "-1")

        if not isinstance(stored_code, str) or stored_code == "-1":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PICKUP_CODE_NOT_GENERATED"
            )

        if not verify_password(code, stored_code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="INCORRECT_PICKUP_CODE"
            )

        household_coordinates = pickup_data.get("coordinates")

        if not household_coordinates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="HOUSEHOLD_COORDINATES_NOT_FOUND"
            )

        reward = await calculate_point(
            reward_policy=admin_data.get("reward_policy"),
            household_address=household_coordinates
        )

        points = reward.get("points") if isinstance(reward, dict) else None

        if (
            not isinstance(points, int)
            or isinstance(points, bool)
            or points < 0
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INVALID_REWARD_CALCULATION"
            )

        collected_at = datetime.now(timezone.utc).isoformat()

        def reserve_collection(current_data):

            if not isinstance(current_data, dict):
                return current_data

            if (
                current_data.get("status") != "accepted"
                or current_data.get("pickup_id") != pickup_id
            ):
                return current_data

            current_code = current_data.get("code", "-1")

            if (
                not isinstance(current_code, str)
                or current_code == "-1"
                or not verify_password(code, current_code)
            ):
                return current_data

            current_data.update({
                "status": "collection_pending_sync",
                "collection_pending": {
                    "pickup_id": pickup_id,
                    "household_id": household_id,
                    "collected_by": user_id,
                    "collected_at": collected_at,
                    "point_rewarded": points
                }
            })

            return current_data

        try:
            reservation_data = household_reference.transaction(
                reserve_collection
            )

        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="COLLECTION_RESERVATION_FAILED"
            ) from error

        if (
            not isinstance(reservation_data, dict)
            or reservation_data.get("status") != "collection_pending_sync"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PICKUP_NOT_AVAILABLE_FOR_COLLECTION"
            )

        reserved_data = reservation_data.get("collection_pending")

        if (
            not isinstance(reserved_data, dict)
            or reserved_data.get("pickup_id") != pickup_id
            or reserved_data.get("household_id") != household_id
            or reserved_data.get("collected_by") != user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="COLLECTION_ALREADY_PENDING"
            )

        points = reserved_data.get("point_rewarded")
        collected_at = reserved_data.get("collected_at")

        if (
            not isinstance(points, int)
            or isinstance(points, bool)
            or points < 0
            or not isinstance(collected_at, str)
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="INVALID_PENDING_COLLECTION"
            )

    audit_data = {
        "household_id": household_id,
        "collected_by": user_id,
        "pickup_id": pickup_id,
        "collected_at": collected_at,
        "point_rewarded": points
    }

    try:
        realtime_db.reference().update({
            f"pickups/accepted/{pickup_id}": None,
            f"pickups/collected/{pickup_id}": True,
            f"workers/{user_id}/accepted/{pickup_id}": None,
            f"audit/collected/{pickup_id}": audit_data
        })

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="COLLECTION_PENDING_SYNC"
        ) from error

    def finalize_collection(current_data):

        if not isinstance(current_data, dict):
            return current_data

        pending = current_data.get("collection_pending")

        if (
            current_data.get("status") != "collection_pending_sync"
            or not isinstance(pending, dict)
            or pending.get("pickup_id") != pickup_id
            or pending.get("household_id") != household_id
            or pending.get("collected_by") != user_id
            or pending.get("point_rewarded") != points
            or pending.get("collected_at") != collected_at
        ):
            return current_data

        current_points = current_data.get("points", 0)

        if (
            not isinstance(current_points, int)
            or isinstance(current_points, bool)
            or current_points < 0
        ):
            return current_data

        current_data.update({
            "status": "idle",
            "code": "-1",
            "pickup_id": None,
            "points": current_points + points,
            "collection_pending": None
        })

        return current_data

    try:
        final_data = household_reference.transaction(
            finalize_collection
        )

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="COLLECTION_PENDING_FINALIZATION"
        ) from error

    # 10. Verify final state
    collected_audit = realtime_db.reference(
        f"audit/collected/{pickup_id}"
    ).get()

    if (
        not isinstance(final_data, dict)
        or final_data.get("status") != "idle"
        or final_data.get("pickup_id") is not None
        or not isinstance(collected_audit, dict)
        or collected_audit.get("collected_by") != user_id
        or collected_audit.get("household_id") != household_id
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="COLLECTION_PENDING_FINALIZATION"
        )

    return {
        "status": True,
        "message": "PICKUP_COLLECTION_CONFIRMED",
        "pickup_id": pickup_id,
        "collection_status": "idle",
        "points_awarded": points,
        "collected_at": collected_at
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

                    if not isinstance(pickup_data, dict):
                        continue

                    household_id = pickup_data.get("household_id")

                    if not household_id:
                        continue

                    household_data = await asyncio.to_thread(
                        realtime_db.reference(
                            f"households/{household_id}"
                        ).get
                    ) or {}

                    if (
                        not isinstance(household_data, dict)
                        or household_data.get("status") != "assigned"
                        or household_data.get("pickup_id") != pickup_id
                    ):
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
                        "coordinates": pickup_data.get("coordinates"),
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