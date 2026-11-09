from fastapi import HTTPException,status,Depends,APIRouter
from datetime import datetime,timezone
from Model.schema import CreateConversation
from Database.db import conversations_db,messages_db
from pymongo import ReturnDocument
from bson import ObjectId
from services.dependencies import active_session
from services.redis_ratelimiter import check_rate_limit


router = APIRouter(prefix="/conversation", tags=["Conversations"])

@router.post('/create')
def create_conversation(conversation : CreateConversation , current_user = Depends(active_session)) :
    my_conversation = conversation.model_dump()

    my_conversation["user_id"] = current_user["_id"]
    my_conversation["createdAt"] = datetime.now(timezone.utc)
    my_conversation["updatedAt"] = datetime.now(timezone.utc)
    my_conversation["summary"] = ""
    my_conversation["summary_through_message_id"] = None
    my_conversation["summary_updated_at"] = None
    res = conversations_db.insert_one(my_conversation)

    if not res.acknowledged :
        raise HTTPException(status_code=status.HTTP_409_CONFLICT , detail="Failed to create conversation")

    created_con = conversations_db.find_one({"_id" : res.inserted_id , "user_id" : current_user["_id"]})

    if not created_con :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND , detail="Conversation not found")

    created_con["id"] = str(created_con.pop("_id"))
    created_con["user_id"] =  str(created_con.pop("user_id"))

    return { "status_code" : status.HTTP_200_OK , "message" : "Conversation created successfully" , "data" : created_con}

@router.get('/all_conversations')
def get_all_conversations(curent_user = Depends(active_session)):

    check_rate_limit(identifier=str(curent_user["_id"]),endpoint="fetch_conversations")

    conversations = list(conversations_db.find({"user_id" : curent_user["_id"]}).sort("updatedAt",-1))

    if not conversations :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND , detail="Conversations not found")
    conversation = []
    for con in conversations :
        con["id"] = str(con.pop("_id"))
        con["user_id"] = str(con.pop("user_id"))
        con["summary_through_message_id"] = str(con.pop("summary_through_message_id")) if con.get("summary_through_message_id") else None
        conversation.append(con)

    return {"status_code":status.HTTP_200_OK ,"message":"succesfully fetched all conversations" ,"data" : conversation }

@router.get('/conversation/{con_id}')
def get_conversation(con_id : str ,current_user = Depends(active_session)) :
    valid_id = ObjectId.is_valid(con_id)

    if not valid_id :
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED ,detail="Invalid conversation iD in token !!!")

    conversation = conversations_db.find_one({"_id" : ObjectId(con_id),"user_id" : current_user["_id"]})

    if not conversation :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND , detail="Conversations not found")

    conversation["id"] = str(conversation.pop("_id"))
    conversation["user_id"] = str(conversation["user_id"])
    conversation["summary_through_message_id"] = str(conversation.pop("summary_through_message_id")) if conversation.get("summary_through_message_id") else None

    return {"status_code" : status.HTTP_200_OK , "message" : "Fetch conversation successfully" , "data" : conversation}

@router.patch('/conversation/{con_id}')
def rename_conversation(con_id : str, title : CreateConversation , currrent_user = Depends(active_session)) :
    valid_id = ObjectId.is_valid(con_id)
    
    if not valid_id :
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED ,detail="Invalid conversation iD in token !!!")
    
    conversation = title.model_dump(exclude_unset=True)
    conversation["updatedAt"] = datetime.now(timezone.utc)

    updated_conversation = conversations_db.find_one_and_update({"_id" : ObjectId(con_id),
                                                                 "user_id" : currrent_user["_id"]},
                                                                 {"$set": conversation},
                                                                 return_document=ReturnDocument.AFTER)


    if not updated_conversation :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND ,detail="Conversation not found")

    
    updated_conversation["id"] = str(updated_conversation.pop("_id"))
    updated_conversation["user_id"] = str(updated_conversation.pop("user_id"))

    return {"status_code" : status.HTTP_200_OK , "message" : "Conversation successfully renamed" , "data" : updated_conversation}

@router.delete('/conversation/{con_id}')
def delete_conversation(con_id :str ,current_user = Depends(active_session)) :

    if not ObjectId.is_valid(con_id) :
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST , detail="Invalid conversation ID")
    
    conversation = conversations_db.find_one({"_id" : ObjectId(con_id),"user_id" : current_user["_id"]})

    if not conversation :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    messages_db.delete_many({"conversation_id" : ObjectId(con_id),"user_id" : current_user["_id"]})


    deleted_conversation = conversations_db.delete_one({"_id" : ObjectId(con_id), "user_id" : current_user["_id"]})

    if  deleted_conversation.deleted_count != 1 :
        raise HTTPException(status_code=status.HTTP_409_CONFLICT ,detail="Conversation Not Deleted successfully ,Please Try again")

    return {"status_code": status.HTTP_200_OK,"message": "Conversation deleted successfully"}

