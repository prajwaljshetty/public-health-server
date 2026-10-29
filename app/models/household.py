from pydantic import BaseModel
from datetime import datetime
from .coordinate import Coordinate

class HousholdCreate(BaseModel):
    username: str
    phoneno: str
    password: str


class HouseholdLogin(BaseModel):
    phoneno: str
    password: str

class HouseholdRequestData(BaseModel):
    time : datetime
    coordinate : Coordinate
    qna: list[int]