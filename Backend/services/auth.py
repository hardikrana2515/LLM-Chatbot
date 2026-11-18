import jwt
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from jwt.exceptions import InvalidTokenError
from config.settings import settings

JWT_SECRET_KEY = settings.jwt_secret_key.get_secret_value()
JWT_ALGORITHM = settings.jwt_algorithm

ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is missing")

if len(JWT_SECRET_KEY) < 32:
    raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters")

def create_access_token(user_id : str ,session_id : str) :
    try :
        now = datetime.now(timezone.utc)

        payload = {
            "sub" : user_id,
            "sid" : session_id,
            "type" : "access",
            "iat" : now,
            "exp" : now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        }

        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        return token
    except Exception as e :
        raise e 

def create_refresh_token() :
    return secrets.token_urlsafe(48)

def hash_refresh_token(token: str) :
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_access_token(token: str):

    try:
        payload = jwt.decode(token,JWT_SECRET_KEY,algorithms=[JWT_ALGORITHM])

        # Only accept access tokens here
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid token type")

        user_id = payload.get("sub")
        session_id = payload.get("sid")

        if not user_id or not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid token payload")

        return (user_id , session_id)
    
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid or expired access token",headers={"WWW-Authenticate": "Bearer"})
