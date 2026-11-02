from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Routers :
from app.router import household , worker

# Firebase
from app.firebase import firestore_db , realtime_db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
