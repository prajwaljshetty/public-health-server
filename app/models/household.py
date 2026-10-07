from pydantic import BaseModel


class HousholdCreate(BaseModel):
    username: str
    phoneno: str
    password: str


class HouseholdLogin(BaseModel):
    phoneno: str
    password: str


