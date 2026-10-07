from pydantic import BaseModel

class WorkerLogin(BaseModel):
    workerid : str
    password : str