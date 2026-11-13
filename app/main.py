from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.router import admin, household, worker
from app.realtime import household_status_hub


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await household_status_hub.start()
    try:
        yield
    finally:
        await household_status_hub.stop()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://10.239.245.28:5173",
        "http://10.239.245.28:8000",
        "http://10.129.77.28:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"message": "Server is running"}


app.include_router(household.router, prefix="/household")
app.include_router(worker.router, prefix="/worker")
app.include_router(admin.router, prefix="/admin")
