from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.firebase import firestore_db, realtime_db
from app.models.worker import PickupAssignmentRequest


router = APIRouter()


@router.get("/pickups/requests")
def get_pickup_requests():
    """Return pickup requests waiting in the administrator's inbox."""
    pickups = realtime_db.reference("pickups/requests").get() or {}
    pickup_statuses = realtime_db.reference("pickups/status").get() or {}

    pickup_requests = []

    for pickup_id, pickup in pickups.items():
        if not isinstance(pickup, dict):
            continue

        household_id = pickup.get("user_id")
        household_data = {}

        if household_id:
            household = (
                firestore_db.collection("households")
                .document(household_id)
                .get()
            )

            if household.exists:
                household_data = household.to_dict() or {}

        status_data = pickup_statuses.get(pickup_id, {})
        if isinstance(status_data, dict):
            pickup_status = status_data.get("status")
        else:
            pickup_status = status_data

        pickup_requests.append({
            "pickupid": pickup.get("pickupid", pickup_id),
            "user_id": household_id,
            "user_name": household_data.get("user_name"),
            "phoneno": household_data.get("phoneno"),
            "time": pickup.get("time"),
            "coordinates": pickup.get("coordinate"),
            "qna": pickup.get("qna", []),
            "status": pickup_status or pickup.get("status", "requested"),
        })

    pickup_requests.sort(
        key=lambda request: request.get("time") or "",
        reverse=True,
    )

    return {
        "status": True,
        "message": "Pickup requests fetched successfully",
        "pickup_requests": pickup_requests,
    }


@router.post("/pickups/{pickup_id}/assign")
def assign_pickup(pickup_id: str, assignment: PickupAssignmentRequest):
    """Atomically claim a pending pickup and assign it to a Firebase worker."""
    worker_document = (
        firestore_db.collection("workers")
        .document(assignment.worker_id)
        .get()
    )

    if not worker_document.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WORKER_NOT_FOUND",
        )

    pickup_request_reference = realtime_db.reference(
        f"pickups/requests/{pickup_id}"
    )
    pickup_request = pickup_request_reference.get()

    if not isinstance(pickup_request, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PICKUP_NOT_FOUND",
        )

    assigned_at = datetime.now(timezone.utc).isoformat()
    pickup_status_reference = realtime_db.reference(
        f"pickups/status/{pickup_id}"
    )

    def claim_pickup(current_data):
        if not isinstance(current_data, dict):
            return current_data
        if current_data.get("status") != "requested":
            return current_data

        return {
            **current_data,
            "status": "assigned",
            "worker_id": assignment.worker_id,
            "assigned_at": assigned_at,
            "assigned_by": "admin",
        }

    claimed_status = pickup_status_reference.transaction(claim_pickup)

    if (
        not isinstance(claimed_status, dict)
        or claimed_status.get("status") != "assigned"
        or claimed_status.get("worker_id") != assignment.worker_id
        or claimed_status.get("assigned_at") != assigned_at
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PICKUP_ALREADY_ASSIGNED",
        )

    worker_data = worker_document.to_dict() or {}
    accepted_pickup = {
        "pickup_id": pickup_id,
        "pickupid": pickup_id,
        "household_id": pickup_request.get("user_id"),
        "household_name": pickup_request.get("user_name"),
        "worker_id": assignment.worker_id,
        "worker_number": worker_data.get("worker_id", ""),
        "worker_name": worker_data.get("user_name", ""),
        "accepted_at": assigned_at,
        "assigned_by": "admin",
        # Flat pickup fields keep the household and worker clients compatible
        # while pickup_data remains the canonical accepted-pickup payload.
        "time": pickup_request.get("time"),
        "coordinate": pickup_request.get("coordinate"),
        "qna": pickup_request.get("qna", []),
        "pickup_data": {
            "time": pickup_request.get("time"),
            "coordinate": pickup_request.get("coordinate"),
            "qna": pickup_request.get("qna", []),
        },
    }

    try:
        # A single multi-location update makes the assignment visible to the
        # worker and removes it from the pending inbox at the same instant.
        realtime_db.reference().update({
            f"pickups/accepted/{pickup_id}": accepted_pickup,
            f"workers/accepted/{assignment.worker_id}/{pickup_id}": True,
            f"pickups/requests/{pickup_id}": None,
        })
    except Exception:
        def rollback_claim(current_data):
            if (
                isinstance(current_data, dict)
                and current_data.get("worker_id") == assignment.worker_id
                and current_data.get("assigned_at") == assigned_at
            ):
                return {
                    "user_id": current_data.get("user_id"),
                    "status": "requested",
                }
            return current_data

        pickup_status_reference.transaction(rollback_claim)
        raise

    return {
        "status": True,
        "message": "Pickup assigned successfully",
        "assignment": accepted_pickup,
    }
