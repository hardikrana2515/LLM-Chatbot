from fastapi import HTTPException,status,Depends,APIRouter
from datetime import datetime,timezone,timedelta
from Model.schema import Login_user,Create_user,Update_password,Update_user,RefreshTokenRequest
from Database.db import user_db,sessions_db
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pwdlib import PasswordHash
from services.auth import create_access_token,create_refresh_token,hash_refresh_token
from services.dependencies import active_session,get_current_session
from services.auth import REFRESH_TOKEN_EXPIRE_DAYS

router = APIRouter(prefix="/auth", tags=["Authentication"])

password_hash = PasswordHash.recommended()

@router.post('/signup')
def signup(user : Create_user) :
    user_data = user.model_dump()

    user_data["password"] = password_hash.hash(user_data["password"])
    user_data["createdAt"] = datetime.now(timezone.utc)
    user_data["updatedAt"] = datetime.now(timezone.utc)

    try :
        res = user_db.insert_one(user_data)
        new_user = user_db.find_one({"_id": res.inserted_id} , {"password" : 0})
        new_user["id"] = str(new_user.pop("_id"))

        return {"status-code" : 200 , "data" : new_user}
    
    except DuplicateKeyError :
        raise HTTPException(status_code=409 , detail="Eamil Already exist , try different one !!!" )
        
@router.post('/login')
def login_user(user : Login_user) :
    user_data = user.model_dump()

    exist_user = user_db.find_one({ "email" : user_data["email"]})

    if not exist_user :
        raise HTTPException(status_code=401 , detail="Invalid email or password")

    valid_pass = password_hash.verify(user_data["password"] ,exist_user["password"])

    if not valid_pass :
        raise HTTPException(status_code=401 , detail="Invalid email or password")
    
    refresh_toekn = create_refresh_token()

    session_data ={"user_id" : exist_user["_id"],
                                            "token_hash" : hash_refresh_token(refresh_toekn),
                                            "createdAt" : datetime.now(timezone.utc),
                                            "updatedAt" : datetime.now(timezone.utc),
                                            "expiresAt": datetime.now(timezone.utc) + timedelta(REFRESH_TOKEN_EXPIRE_DAYS),
                                            "revoked" : False
                                            }
    session_result = sessions_db.insert_one(session_data)

    session_id = str(session_result.inserted_id)

    access_token = create_access_token(str(exist_user["_id"]),session_id)


    exist_user["id"] = str(exist_user.pop("_id"))

    res ={
        "id": exist_user["id"],
        "Full name": exist_user["first_name"] + " " + exist_user["last_name"],
        "email": exist_user["email"]
        }

    return {"status_code" : status.HTTP_200_OK , "message" : "User Logged in " ,"data" : res, "access_token": access_token ,"refresh_token" : refresh_toekn,"token_type" : "bearer"}
    
@router.get('/get_profile')
def get_profile( current_user : dict = Depends(active_session)) :

    current_user["id"] = str(current_user.pop("_id"))
    del current_user["password"]
    return {"status_code" : status.HTTP_200_OK , "message" : "Authenticated successfully" , "data" : current_user}

@router.put('/update-profile')
def update_profile(user : Update_user , current_user = Depends(active_session) ) :

    user_data = user.model_dump(exclude_unset=True) 

    if not user_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No profile fields provided")

    user_data["updatedAt"] = datetime.now(timezone.utc)

    try :
        user_db.update_one({"_id" : current_user["_id"]},{"$set": user_data})
        updated_user = user_db.find_one({"_id" : current_user["_id"]} ,{"password" : 0})

    except DuplicateKeyError :    
        raise HTTPException(status_code=status.HTTP_409_CONFLICT , detail="email already exist,try another one !!!")
    
    if not updated_user :
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND , detail="User not found")
    
    updated_user["id"] = str(updated_user.pop("_id"))

    return {"status_code":status.HTTP_200_OK , "message" : "User updated successfully " , "data" : updated_user}

@router.put('/password')
def updatePassword(password : Update_password ,current_user=Depends(active_session)) :
    
    user_data = password.model_dump()
    verify_oldpass = password_hash.verify(user_data["oldpassword"],current_user["password"])

    if user_data["oldpassword"] != user_data["newpassword"] :
        if verify_oldpass :
            new_pass = password_hash.hash(user_data["newpassword"])
            user_db.update_one({"_id" : ObjectId(current_user["_id"])} , 
                               {"$set" : {"password" : new_pass , "updatedAt" : datetime.now(timezone.utc)}})        
        else :
            raise HTTPException(status_code=401, detail="Old Password is Incorrect !!!")
    else :
         raise HTTPException(status_code=400 , detail="Old password is same as new password")

    return {"status_code" : status.HTTP_200_OK , "message" : "Password Updated Successfully !!!"}

@router.post('/logout')
def logout_user(current_session : dict = Depends(get_current_session)) :

    result = sessions_db.update_one({"_id": current_session["_id"],"revoked": False},
        {"$set": {
                "revoked": True,
                "updatedAt": datetime.now(timezone.utc)
            }})
    
    if result.modified_count == 0 :
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED , detail="No active session found")
    
    return {"status_code": status.HTTP_200_OK,"message": "User logged out successfully"}

@router.post("/refresh")
def refresh_access_token(data: RefreshTokenRequest):

    token_hash = hash_refresh_token(data.refresh_token)

    new_refresh_token = create_refresh_token()

    updated_session = sessions_db.find_one_and_update({"token_hash": token_hash,"revoked": False,"expiresAt": {"$gt": datetime.now(timezone.utc)}},
        { "$set": {"token_hash": hash_refresh_token(new_refresh_token),
                   "updatedAt": datetime.now(timezone.utc)
                   }},
        return_document=ReturnDocument.AFTER)

    if not updated_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid or expired refresh token")
    
    access_token = create_access_token(str(updated_session["user_id"]),str(updated_session["_id"]))

    return {
        "status_code": status.HTTP_200_OK,
        "message": "Access token refreshed successfully",
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }



