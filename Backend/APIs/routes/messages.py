from fastapi import HTTPException,status,Depends,APIRouter
from datetime import datetime,timezone
from Model.schema import CreateMessages,MessageStatus
from Database.db import messages_db,conversations_db
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError,ConnectionFailure
from bson import ObjectId
from services.dependencies import active_session
from services.llm import generate_response
from groq import Groq,APIConnectionError,APITimeoutError,RateLimitError,APIStatusError
from services.token_manager import build_chat_context,count_message_tokens,SAFETY_MARGIN
from services.usage_quota import reserve_tokens,reconcile_tokens,release_tokens
from config.usage_limits import USAGE_LIMITS
from services.summarizer import update_conversation_summary
from services.usage_tracker import record_llm_usage
from fastapi import Header
import logging
from services.redis_ratelimiter import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["Messages"])

@router.post('/create/{con_id}/message')
def message(con_id : str , message : CreateMessages ,idempotency_key: str = Header(alias="Idempotency-Key"),current_user = Depends(active_session)) :
    valid_id = ObjectId.is_valid(con_id)

    if not valid_id :
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST ,detail="Invalid conversation iD in token !!!")
    
    try:
        conversation = conversations_db.find_one({
            "_id": ObjectId(con_id),
            "user_id": current_user["_id"]
        })

    except ConnectionFailure:
        logger.exception(
            "MongoDB connection failed while fetching conversation"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is temporarily unavailable. Please try again."
        )
    if not conversation :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    check_rate_limit(identifier=str(current_user["_id"]),endpoint="create_message")

    try :
        # Check idempotency before reserving tokens.
        existing_message = messages_db.find_one({
            "user_id": current_user["_id"],
            "client_message_id": idempotency_key,
            "conversation_id": ObjectId(con_id),
            "role": "user"
        })
    except ConnectionFailure :
        logger.exception(
            "MongoDB connection failed during idempotency lookup"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is temporarily unavailable. Please try again."
        )

    if existing_message:

        existing_assistant_message = messages_db.find_one({
            "user_id": current_user["_id"],
            "conversation_id": ObjectId(con_id),
            "in_reply_to_message_id": existing_message["_id"],
            "role": "assistant"
        })

        if not existing_assistant_message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This request is already being processed. Retry using the same key."
            )

        if existing_assistant_message["status"] == MessageStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Your AI response is still being generated."
            )

        if existing_assistant_message["status"] == MessageStatus.FAILED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The previous AI generation failed. Please start a new request."
            )

        existing_message["id"] = str(existing_message.pop("_id"))
        existing_message["user_id"] = str(existing_message.pop("user_id"))
        existing_message["conversation_id"] = str(existing_message.pop("conversation_id"))

        existing_assistant_message["id"] = str(existing_assistant_message.pop("_id"))
        existing_assistant_message["user_id"] = str(existing_assistant_message.pop("user_id"))
        existing_assistant_message["conversation_id"] = str(existing_assistant_message.pop("conversation_id"))
        existing_assistant_message["in_reply_to_message_id"] = str(
            existing_assistant_message.pop("in_reply_to_message_id")
        )

        return {
            "status_code": status.HTTP_200_OK,
            "message": "Existing response returned successfully",
            "data": {
                "user_message": existing_message,
                "assistant_message": existing_assistant_message
            }
        }

    user_message = message.model_dump()

    user_message["conversation_id"] = ObjectId(con_id)
    user_message["user_id"] = current_user["_id"]
    user_message["role"] = "user"
    user_message["is_deleted"] = False
    user_message["status"] = MessageStatus.COMPLETED.value
    user_message["client_message_id"] = idempotency_key
    user_message["createdAt"] = datetime.now(timezone.utc)
    user_message["updatedAt"] = datetime.now(timezone.utc)
    user_message["deletedAt"] = None

    history_query = {
            "conversation_id": ObjectId(con_id),
            "user_id": current_user["_id"],
            "role": {"$in": ["user", "assistant"]},
            "is_deleted": False,
            "status": MessageStatus.COMPLETED.value
        }

    last_summary_id = conversation.get("summary_through_message_id")

    if last_summary_id:
        cursor_message = messages_db.find_one({
                "_id": last_summary_id,
                "conversation_id": ObjectId(con_id),
                "user_id": current_user["_id"]
            })

        if not cursor_message:
            raise HTTPException(
                status_code=500,
                detail="Conversation summary cursor could not be found"
            )

        history_query["$or"] = [
                {"createdAt": {"$gt": cursor_message["createdAt"]}},
                {
                    "createdAt": cursor_message["createdAt"],
                    "_id": {"$gt": last_summary_id}
                }
            ]


    try:
        history = list(
            messages_db.find(history_query)
            .sort([("createdAt", -1), ("_id", -1)])
            .limit(50)
        )

    except ConnectionFailure:
        logger.exception(
            "MongoDB connection failed during message history retrieval"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is temporarily unavailable. Please try again."
        )

    history.reverse()

    SYSTEM_PROMPT = """ 
        You are a helpful AI assistant.
        Answer clearly and accurately.
        """
    conversation_summary = conversation.get("summary", "")

    chat_history = build_chat_context( system_prompt=SYSTEM_PROMPT,
                                        summary=conversation_summary,
                                        conversation_history=history,
                                        current_user_message=message.content)

    # Estimate tokens required for this LLM request
    estimated_prompt_tokens = count_message_tokens(chat_history)


    requested_tokens = (
        estimated_prompt_tokens
        + USAGE_LIMITS["max_output_tokens"]
        + SAFETY_MARGIN
    )

    # Reserve tokens before calling the LLM
    reservation = reserve_tokens(
        user_id=str(current_user["_id"]),
        requested_tokens=requested_tokens
    )

    reservation_id = reservation["reservation_id"]

    try:
        res = messages_db.insert_one(user_message)

    except DuplicateKeyError:
        release_tokens(
            user_id=str(current_user["_id"]),
            reservation_id=reservation_id
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This request is already being processed."
        )
    except ConnectionFailure:
        logger.exception(
            "MongoDB connection failed during user message insertion"
        )

        try:
            release_tokens(
                user_id=str(current_user["_id"]),
                reservation_id=reservation_id
            )
        except Exception:
            logger.exception(
                "Failed to release reservation after MongoDB connection failure"
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is temporarily unavailable. Please try again."
        )

    except Exception:
        try:
            release_tokens(
                user_id=str(current_user["_id"]),
                reservation_id=reservation_id
            )
        except Exception:
            logger.exception("Failed to release reservation after user message insertion error")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user message"
        )

    if not res.acknowledged:
        release_tokens(
            user_id=str(current_user["_id"]),
            reservation_id=reservation_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User message insertion was not acknowledged"
        )

    created_message = messages_db.find_one({
        "_id": res.inserted_id,
        "user_id": current_user["_id"],
        "conversation_id": ObjectId(con_id)
    })

    if not created_message:
        release_tokens(
            user_id=str(current_user["_id"]),
            reservation_id=reservation_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve created user message"
        )

    conversations_db.update_one(
        {
            "_id": ObjectId(con_id),
            "user_id": current_user["_id"]
        },
        {
            "$set": {
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )


    assistant_message = {
            "conversation_id": ObjectId(con_id),
            "user_id": current_user["_id"],
            "in_reply_to_message_id": res.inserted_id,
            "role": "assistant",
            "content": "",  # Placeholder for the assistant's response
            "is_deleted": False,
            "status": MessageStatus.PENDING.value, #Pending Status
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "deletedAt": None
        }

    try:
        assistant_res = messages_db.insert_one(assistant_message)

    except ConnectionFailure:
        logger.exception(
            "MongoDB connection failed during assistant message insertion"
        )

        try:
            release_tokens(
                user_id=str(current_user["_id"]),
                reservation_id=reservation_id
            )
        except Exception:
            logger.exception(
                "Failed to release reservation after assistant insertion failure"
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is temporarily unavailable. Please try again."
        )

    except Exception:
        try:
            release_tokens(
                user_id=str(current_user["_id"]),
                reservation_id=reservation_id
            )
        except Exception:
            logger.exception(
                "Failed to release reservation after assistant insertion error: %s",
                reservation_id
            )

        raise HTTPException(
            status_code=500,
            detail="Failed to create assistant message"
        )

    if not assistant_res.acknowledged:
        try:
            release_tokens(
                user_id=str(current_user["_id"]),
                reservation_id=reservation_id
            )
        except Exception:
            logger.exception(
                "Failed to release reservation after unacknowledged insertion: %s",
                reservation_id
            )

        raise HTTPException(
            status_code=500,
            detail="Failed to create assistant message"
        )

    try:
        llm_result = generate_response(chat_history)
        assistant_response = llm_result.get("content")

        usage_data = llm_result.get("usage", {})
        timing_data = llm_result.get("timing", {})

        model_name = llm_result.get("model")
        request_id = llm_result.get("request_id")

        if not isinstance(assistant_response, str) or not assistant_response.strip():
            raise ValueError("LLM returned an empty response")

    except APITimeoutError:
        logger.exception("Groq API timeout")
        error_status = status.HTTP_504_GATEWAY_TIMEOUT
        error_message = "AI response timed out. Please try again."

    except RateLimitError:
        logger.exception("Groq API rate limit exceeded")
        error_status = status.HTTP_503_SERVICE_UNAVAILABLE
        error_message = "AI service is temporarily busy. Please try again."

    except APIConnectionError:
        logger.exception("Unable to connect to Groq")
        error_status = status.HTTP_502_BAD_GATEWAY
        error_message = "Unable to connect to AI service."

    except APIStatusError:
        logger.exception("Groq API returned an error")
        error_status = status.HTTP_502_BAD_GATEWAY
        error_message = "AI service returned an error."

    except Exception:
        logger.exception("Unexpected LLM generation error")
        error_status = status.HTTP_502_BAD_GATEWAY
        error_message = "Failed to generate AI response."

    else:
        error_status = None
        error_message = None

    if error_status is not None:

        try:
            release_tokens(
                user_id=str(current_user["_id"]),
                reservation_id=reservation_id
            )
        except Exception:
            logger.exception(
                "Failed to release token reservation: %s",
                reservation_id
            )

        update_res = messages_db.update_one(
            {
                "_id": assistant_res.inserted_id,
                "user_id": current_user["_id"],
                "conversation_id": ObjectId(con_id),
                "status": MessageStatus.PENDING.value
            },
            {
                "$set": {
                    "status": MessageStatus.FAILED.value,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )

        if update_res.matched_count == 0:
            logger.error("Unable to mark assistant message as failed")

        raise HTTPException(
            status_code=error_status,
            detail=error_message
        )
    
    try:
        reconciliation = reconcile_tokens(
            user_id=str(current_user["_id"]),
            reservation_id=reservation_id,
            actual_tokens=usage_data["total_tokens"]
        )

    except Exception:
        logger.exception(
            "Failed to reconcile token reservation: %s",
            reservation_id
        )
    
    try:
        record_llm_usage(
            user_id=current_user["_id"],
            conversation_id=ObjectId(con_id),
            message_id=assistant_res.inserted_id,
            llm_result=llm_result
        )

    except Exception:
        logger.exception("Failed to record LLM usage")

    #update the assistant_message to Completed
    update_res = messages_db.update_one({"_id" : assistant_res.inserted_id,"user_id": current_user["_id"], 
                            "conversation_id": ObjectId(con_id) ,"status" : MessageStatus.PENDING.value},
                                           {"$set" :
                                                {"content" : assistant_response,
                                                 "status" : MessageStatus.COMPLETED.value,
                                                 "updatedAt" : datetime.now(timezone.utc)
                                                }
                                            })

    if update_res.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Assistant message could not be updated")

    assistant_message_completed = messages_db.find_one({"_id": assistant_res.inserted_id, "user_id": current_user["_id"],
                                                        "conversation_id": ObjectId(con_id)})

    if not assistant_message_completed:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve assistant message")

    try:
        conversation = conversations_db.find_one({
            "_id": ObjectId(con_id),
            "user_id": current_user["_id"]
        })

        update_conversation_summary(conversation)

    except Exception:
        logger.exception("Failed to update conversation summary")


    created_message["id"] = str(created_message.pop("_id"))
    created_message["user_id"] =  str(created_message.pop("user_id"))
    created_message["conversation_id"] = str(created_message.pop("conversation_id"))

    assistant_message_completed["id"] = str(assistant_message_completed.pop("_id"))
    assistant_message_completed["user_id"] = str(assistant_message_completed.pop("user_id"))
    assistant_message_completed["conversation_id"] = str(assistant_message_completed.pop("conversation_id"))
    assistant_message_completed["in_reply_to_message_id"] = str(assistant_message_completed.pop("in_reply_to_message_id")) if assistant_message_completed.get("in_reply_to_message_id") else None

    return { "status_code" : status.HTTP_201_CREATED , "message" : "message created successfully" ,
             "data" : {"user_message" : created_message , "assistant_message" : assistant_message_completed}}

@router.get('/all_messages/{con_id}/messages')
def get_all_messages(con_id : str , current_user = Depends(active_session)) :
    valid_id = ObjectId.is_valid(con_id)

    if not valid_id :
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED ,detail="Invalid conversation iD in token !!!")


    conversation = conversations_db.find_one({"_id" : ObjectId(con_id),"user_id" : str(current_user["_id"])})
    if not conversation :
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    check_rate_limit(identifier=current_user["_id"],endpoint="fetch_messages")

    messages = list(messages_db.find({"user_id" : current_user["_id"] ,"conversation_id" : ObjectId(con_id) , "is_deleted" : False}).sort("createdAt",1))

    All_messages = []
    for msg in messages :
        msg["id"] = str(msg.pop("_id"))
        msg["user_id"] = str(msg.pop("user_id"))
        msg["conversation_id"] = str(msg.pop("conversation_id"))
        msg["in_reply_to_message_id"] = str(msg.pop("in_reply_to_message_id")) if msg.get("in_reply_to_message_id") else None
        
        All_messages.append(msg)
    return { "status_code" : status.HTTP_200_OK , "message" : "Messages fetched successfully" , "Conversation" : conversation["title"] ,"data" : All_messages}

@router.patch('/{con_id}/message/{msg_id}')
def delete_message(con_id : str , msg_id : str , current_user = Depends(active_session)) :
    valid_con_id = ObjectId.is_valid(con_id)
    valid_msg_id = ObjectId.is_valid(msg_id)

    if not valid_con_id or not valid_msg_id :
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST ,detail="Invalid conversation or message iD in token !!!")
    
    deleted_message = messages_db.find_one_and_update({"_id" : ObjectId(msg_id) ,"user_id" : current_user["_id"] ,"conversation_id" : ObjectId(con_id), "is_deleted" : False},
                                                      {"$set" : {"is_deleted" : True , 
                                                                 "deletedAt" : datetime.now(timezone.utc),
                                                                 "updatedAt" : datetime.now(timezone.utc)}} , 
                                                        return_document=ReturnDocument.AFTER)

    if not deleted_message :
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND , detail="Message not found")

    deleted_message["id"] = str(deleted_message.pop("_id"))
    deleted_message["user_id"] =  str(deleted_message.pop("user_id"))
    deleted_message["conversation_id"] = str(deleted_message.pop("conversation_id"))

    return { "status_code" : status.HTTP_200_OK , "message" : "message deleted successfully"}

