# OS :
import os
from pathlib import Path
from dotenv import load_dotenv

# HTTP :
from fastapi import Depends , HTTPException, status

# Date Time :
from datetime import datetime, timedelta, timezone

# Java Web Token :
import jwt

# HTTP Bearer :
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

security = HTTPBearer()

configuration = {
    "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY"),
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": 15,
    "REFRESH_TOKEN_EXPIRE_DAYS" : 30
}

if not configuration["JWT_SECRET_KEY"]:
    raise RuntimeError("JWT_SECRET_KEY is missing from .env")

def get_current_user(credentials : HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    payload = validate_token(token = token , tokentype = "access")

    if not payload :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_OR_EXPIRED_ACCESS_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload

def get_refresh_token( credentials : HTTPAuthorizationCredentials = Depends(security)):

    token = credentials.credentials

    payload = validate_token(token = token , tokentype = "refresh")

    if not payload :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_OR_EXPIRED_REFRESH_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload
    
def create_access_token(user_id: str , role : str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        days=configuration["ACCESS_TOKEN_EXPIRE_MINUTES"]
    )

    payload = {
        "sub": user_id,
        "type": "access",
        "role": role,
        "iat": now,
        "exp": expire,
    }

    token = jwt.encode(
        payload = payload,
        key = configuration["JWT_SECRET_KEY"],
        algorithm = configuration["ALGORITHM"],
    )

    return token

def create_refresh_token(user_id: str , role : str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        days=configuration["REFRESH_TOKEN_EXPIRE_DAYS"]
    )

    payload = {
        "sub": user_id,
        "type": "refresh",
        "role": role,
        "iat": now,
        "exp": expire,
    }

    token = jwt.encode(
        payload = payload,
        key = configuration["JWT_SECRET_KEY"],
        algorithm = configuration["ALGORITHM"],
    )

    return token

def validate_token(token: str , tokentype: str) -> dict | None:
    try :
        payload = jwt.decode(
            jwt = token ,
            key = configuration["JWT_SECRET_KEY"] ,
            algorithms = [configuration["ALGORITHM"]],
        )

        if payload.get("type") != tokentype :
            return None

        if not payload.get("sub") :
            return None

        return payload
     
    except jwt.InvalidTokenError :
        return None
