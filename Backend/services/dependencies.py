from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
from datetime import datetime,timezone
from Database.db import user_db,sessions_db
from services.auth import verify_access_token

# Extract Bearer token from Authorization header
bearer_scheme = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    # Extract token string
    token = credentials.credentials

    # Verify token and extract user ID
    user_id = verify_access_token(token)

    if not ObjectId.is_valid(user_id) :
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED ,detail="Invalid user ID in token !!!")

    current_user = user_db.find_one({"_id" : ObjectId(user_id)})

    if current_user is None : 
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED , detail="User no longer exists !!!")

    return current_user

def active_session(current_user : dict = Depends(get_current_user)) :

    valid_session = sessions_db.find_one({"user_id" : current_user["_id"],
                                          "revoked" : False,
                                          "expiresAt" : {"$gt" : datetime.now(timezone.utc)}})
    
    if not valid_session :
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED ,detail="User does not logged-in !!")

    return current_user
