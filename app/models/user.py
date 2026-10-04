from pydantic import BaseModel


class UserRegister(BaseModel):
    username: str
    role : str
    phoneno: str
    password: str


class UserLogin(BaseModel):
    role : str
    phoneno: str
    password: str


