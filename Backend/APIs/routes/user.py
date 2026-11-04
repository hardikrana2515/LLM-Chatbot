from fastapi import HTTPException,status,Depends,APIRouter
from datetime import datetime,timezone
from Model.schema import Create_user,Update_user,Update_password
from Database.db import user_db
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from pwdlib import PasswordHash



router = APIRouter(prefix="/TESTuser",tags=["Users"])

password_hash = PasswordHash.recommended()

@router.get('/test/users')
def get_all_users() :
    users = user_db.find({},{"password":0}) 
    res = []
    for user in users :
        user["id"]=str(user["_id"])   
        del user["_id"]
        res.append(user)

    return {"status_code" : 200 , "data" : res}

@router.get('/test/user/{user_id}')
def get_user(user_id : str) :

    if not ObjectId.is_valid(user_id) :
        raise HTTPException(status_code=400 , detail='Invalid user id')

    user = user_db.find_one({"_id" : ObjectId(user_id)} ,{"password" : 0})

    if user :
        user["id"] = str(user.pop("_id"))
        return {"status_code" : 200 , "data" : user}
    else :
        raise HTTPException(status_code=404 , detail="user Not Found !!!")
    

@router.post('/test/user')
def createUser(user : Create_user) :
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

    
@router.put('/test/user/{user_id}')
def updateUser(user_id : str ,user : Update_user) :
    if not ObjectId.is_valid(user_id) :
            raise HTTPException(status_code=400 , detail='Invalid user id')

    user_exist = user_db.find_one({"_id":ObjectId(user_id)})
    if user_exist :
        user_data = user.model_dump(exclude_unset=True)

        if not user_data :
            raise HTTPException(status_code=400 , detail="User Data not Provided !!")
        try :
            user_data["updatedAt"] = datetime.now(timezone.utc)
            user_db.update_one({"_id" : ObjectId(user_id)},{"$set" : user_data})

            updated_user = user_db.find_one({"_id" : ObjectId(user_id)},{"password" : 0 })
            updated_user["id"] = str(updated_user.pop("_id"))

        except DuplicateKeyError :
            raise HTTPException(status_code=409 , detail="Eamil Already exist , try different one !!!" )
    else :
        raise HTTPException(status_code=404 , detail="user Not Found !!!")

    return {"status-code" : 200 , "message": "User Updated Successfully", "data" : updated_user}

@router.delete('/test/user/{user_id}')
def deleteUser(user_id : str ) :
    if not ObjectId.is_valid(user_id) :
                    raise HTTPException(status_code=400 , detail='Invalid user id')
    
    user_exist = user_db.find_one({"_id":ObjectId(user_id)})
    
    if user_exist :
        deleted_user = user_db.delete_one({"_id" : ObjectId(user_id)})
    else :
                raise HTTPException(status_code=404 , detail="user Not Found !!!")
    
    if deleted_user :
         return {"status_code" : 200 , "message" : "User Deleted Successfully !!!"}
    else :
         raise HTTPException(status_code= 400 , detail="User can not deleted !!!")
    

@router.put('/test/password/{user_id}')
def updatePassword(user_id : str , password : Update_password) :
    if not ObjectId.is_valid(user_id) :
        raise HTTPException(status_code=400 , detail='Invalid user id')    

    user_exist = user_db.find_one({"_id":ObjectId(user_id)})
    
    if user_exist :
        user_data = password.model_dump()
        verify_oldpass = password_hash.verify(user_data["oldpassword"],user_exist["password"])

        if user_data["oldpassword"] != user_data["newpassword"] :
            if verify_oldpass :
                new_pass = password_hash.hash(user_data["newpassword"])
                user_db.update_one({"_id" : ObjectId(user_id)} , {"$set" : {"password" : new_pass , "updatedAt" : datetime.now(timezone.utc)}})        
            else :
                raise HTTPException(status_code=401, detail="Old Password is Incorrect !!!")
        else :
             raise HTTPException(status_code=400 , detail="Old password is same as new password")

    return {"status_code" : 200 , "message" : "Password Updated Successfully !!!"}

