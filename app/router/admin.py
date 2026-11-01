from fastapi import APIRouter

from app.firebase import firestore_db, realtime_db


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
