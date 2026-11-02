from pydantic import BaseModel


class WorkerUpdate(BaseModel):
    """Administrator-editable worker fields."""

    name: str = Field(min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=6)

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