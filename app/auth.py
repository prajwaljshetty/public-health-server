# OS :
import os
from dotenv import load_dotenv

# HTTP :
from fastapi import Depends , HTTPException, status

# Date Time :
from datetime import datetime, timedelta, timezone

# Java Web Token :
import jwt

# HTTP Bearer :
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv()

security = HTTPBearer()

configuration = {
    "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY"),
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": 15,
    "REFRESH_TOKEN_EXPIRE_DAYS" : 30
}

# Secret key ( .env de store maldhe )
if not configuration["JWT_SECRET_KEY"]:
    raise RuntimeError("JWT_SECRET_KEY is missing from .env")

def get_current_user(credentials : HTTPAuthorizationCredentials = Depends(security)):
    # Get the access token from HTTP header (Authorization : bearer < access_token >)
    token = credentials.credentials

    print("token :" , token)
    # Validate Token and get the payload
    payload = validate_token(token = token , tokentype = "access")

    # Invlaid token
    if not payload :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    #return payload
    return payload

def get_refresh_token( credentials : HTTPAuthorizationCredentials = Depends(security)):

    # Get the refresh token from HTTP header (Authorization : bearer < refresh_token >)
    token = credentials.credentials

    # Validate Token and get the payload
    payload = validate_token(token = token , tokentype = "refresh")

    # Invlaid token
    if not payload :
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_OR_EXPIRED_REFRESH_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    #return payload
    return payload
    
def create_access_token(user_id: str) -> str:
    # Token expiration: 15 minutes
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=configuration["ACCESS_TOKEN_EXPIRE_MINUTES"]
    )

    # JWT payload
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": expire,
    }

    # Generate and sign the JWT
    token = jwt.encode(
        payload = payload,
        key = configuration["JWT_SECRET_KEY"],
        algorithm = configuration["ALGORITHM"],
    )

    return token

def create_refresh_token(user_id: str) -> str:
    # Refresh token expiration: 30 days
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        days=configuration["REFRESH_TOKEN_EXPIRE_DAYS"]
    )

    # JWT payload
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": expire,
    }

    # Generate and sign the JWT
    token = jwt.encode(
        payload = payload,
        key = configuration["JWT_SECRET_KEY"],
        algorithm = configuration["ALGORITHM"],
    )

    return token

def validate_token(token: str , tokentype: str) -> dict | None:
    try :
        # Decode payload
        payload = jwt.decode(
            jwt = token ,
            key = configuration["JWT_SECRET_KEY"] ,
            algorithms = [configuration["ALGORITHM"]],
        )

        # Token type check
        if payload.get("type") != tokentype :
            return None

        # Valid user
        if not payload.get("sub") :
            return None

        # Payload
        return payload
     
    except jwt.InvalidTokenError :
        return None
