from pydantic import BaseModel


class UserRegister(BaseModel):
    username: str
    phoneno: str
    password: str


class UserLogin(BaseModel):
    phoneno: str
    password: str


