from fastapi import FastAPI

# Routers :
from app.router import household , worker

# Firebase
from app.firebase import firestore_db , realtime_db

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Server is running"}

app.include_router(
    household.router,
    prefix="/household"
)

app.include_router(
    worker.router,
    prefix='/worker'
)