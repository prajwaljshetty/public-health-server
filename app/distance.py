import os
import httpx

from fastapi import HTTPException, status


async def calculate_road_distance( base_address: dict , household_address: dict ) -> float:

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MAPS_API_KEY_NOT_CONFIGURED"
        )

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.distanceMeters"
    }

    payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": base_address["latitude"],
                    "longitude": base_address["longitude"]
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": household_address["latitude"],
                    "longitude": household_address["longitude"]
                }
            }
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE"
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload
            )

        response.raise_for_status()

        data = response.json()

        routes = data.get("routes", [])

        if not routes:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="ROAD_ROUTE_NOT_FOUND"
            )

        return routes[0]["distanceMeters"]

    except httpx.HTTPStatusError as error:
        print("Google HTTP error:", error.response.status_code)
        print("Google error details:", error.response.text)

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GOOGLE_ROUTES_API_ERROR"
        )

    except httpx.RequestError as error:
        print("Google connection error:", str(error))

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GOOGLE_ROUTES_CONNECTION_FAILED"
        )

    except HTTPException:
        raise

    except (KeyError, IndexError, ValueError) as error:
        print("Google response parsing error:", str(error))

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="INVALID_GOOGLE_ROUTES_RESPONSE"
        )
