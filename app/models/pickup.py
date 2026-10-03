from pydantic import BaseModel

# Coordinate :
from app.models.coordinate import Coordinate

class PickupRequest(BaseModel):
    userid: str
    time: str
    coordinates: Coordinate
    attribute: tuple[int, int, int]