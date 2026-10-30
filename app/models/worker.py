from pydantic import BaseModel

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
    time : str