from fastapi import FastAPI

# Routers :
from app.router import user

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Server is running"}

app.include_router(
    user.router,
    prefix="/user"
)