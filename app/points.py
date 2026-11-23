
# HTTP :
from fastapi import HTTPException, status

# Math :
from math import ceil, isfinite

# Distance Calculator :
from .distance import calculate_road_distance


def error(status_code: int, detail: str):
    raise HTTPException(
        status_code=status_code,
        detail=detail
    )

def validate_point(point: int) -> bool:
    return (
        not isinstance(point, int)
        or isinstance(point, bool)
        or point < 0
    )

def validate_coordinates(coordinates: dict) -> bool:

    if not isinstance(coordinates, dict):
        return False

    latitude = coordinates.get("latitude")
    longitude = coordinates.get("longitude")

    if (
        not isinstance(latitude, (int, float))
        or isinstance(latitude, bool)
        or not isinstance(longitude, (int, float))
        or isinstance(longitude, bool)
    ):
        return False

    if not isfinite(latitude) or not isfinite(longitude):
        return False

    return (
        -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )

async def calculate_point(
    reward_policy: dict,
    household_address: dict
) -> dict:

    if not isinstance(reward_policy, dict) or not reward_policy:
        error(
            status.HTTP_404_NOT_FOUND,
            "REWARD_POLICY_NOT_FOUND"
        )

    policy_type = reward_policy.get("type")

    if policy_type == "constant":

        points = reward_policy.get("point")

        if validate_point(points):
            error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "INVALID_REWARD_POLICY"
            )

        return {"points": points}

    elif policy_type == "relative":

        min_point = reward_policy.get("min_point")
        base_address = reward_policy.get("base_address")

        if (
            validate_point(min_point)
            or not validate_coordinates(base_address)
            or not validate_coordinates(household_address)
        ):
            error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "INVALID_REWARD_POLICY"
            )

        distance = await calculate_road_distance(
            base_address,
            household_address
        )

        distance_km = distance / 1000

        points = max(min_point, ceil(distance_km))

        return {
            "points": points,
            "distance_meters": distance,
            "distance_km": round(distance_km, 2)
        }

    else:
        error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INVALID_REWARD_POLICY"
        )
