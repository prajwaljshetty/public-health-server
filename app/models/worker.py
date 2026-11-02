from pydantic import BaseModel, Field


class WorkerCreate(BaseModel):
    """Fields required when an administrator creates a worker account."""

    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6)

class WorkerRegister(BaseModel):
    worker_id: str
    user_name: str
    phoneno: str
    password: str

class WorkerLogin(BaseModel):
    worker_id : str
    password : str


class PickupAcceptanceRequest(BaseModel):
    pickup_id : str
