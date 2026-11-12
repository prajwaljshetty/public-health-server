from pydantic import BaseModel, Field

class WorkerUpdate(BaseModel):
    worker_id: str
    name: str
    password: str

class WorkerRegister(BaseModel):
    worker_id: str
    user_name: str
    phoneno: str
    password: str

class WorkerLogin(BaseModel):
    worker_id: str
    password: str

class PickupAcceptanceRequest(BaseModel):
    pickup_id: str

class PickupAssignmentRequest(BaseModel):
    worker_id: str = Field(min_length=1)
