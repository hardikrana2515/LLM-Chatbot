from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
from datetime import datetime,timezone
from Database.db import user_db,sessions_db
from services.auth import verify_access_token

# Extract Bearer token from Authorization header
bearer_scheme = HTTPBearer()

def get_auth_context(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    # Extract token string
    token = credentials.credentials

    # Verify token and extract user ID
    user_id,session_id = verify_access_token(token)
  
    if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(session_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED ,detail="Invalid user ID or session ID in token !!!")

    user_object_id = ObjectId(user_id)
    session_object_id = ObjectId(session_id)
    
    current_user = user_db.find_one({"_id" : user_object_id})

    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="User no longer exists")

    valid_session = sessions_db.find_one({
        "_id": session_object_id,
        "user_id": user_object_id,
        "revoked": False,
        "expiresAt": {"$gt": datetime.now(timezone.utc)}
    })

    if not valid_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid, expired or revoked session")

    return {
        "user": current_user,
        "session": valid_session
        }

def get_current_user(auth=Depends(get_auth_context)):
    return auth["user"]

def get_current_session(auth=Depends(get_auth_context)):
    return auth["session"]

def active_session(current_user = Depends(get_current_user)):
    return current_user

