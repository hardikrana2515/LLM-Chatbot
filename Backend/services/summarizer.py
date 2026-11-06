from services.llm import generate_response
from Database.db import messages_db,conversations_db
from datetime import datetime,timezone
from Model.schema import MessageStatus
from services.token_manager import (count_message_tokens,select_messages_for_summary,
                                    RECENT_HISTORY_BUDGET,SUMMARY_TRIGGER_TOKENS   
                                    )

def generate_conversation_summary(existing_summary: str,new_messages: list) -> str:

    conversation_text = ""

    for message in new_messages:
        conversation_text += (
            f'{message["role"]}: {message["content"]}\n'
        )

    summarization_prompt = f"""
        You are a conversation summarization assistant.

        Your task is to maintain an accurate, concise summary
        of the conversation.

        Existing summary:
        {existing_summary if existing_summary else "No previous summary."}

        New conversation messages:
        {conversation_text}

        Instructions:
        1. Preserve important user goals and requirements.
        2. Preserve technical decisions, preferences and constraints.
        3. Preserve relevant facts, progress and unresolved problems.
        4. Remove repetition and unnecessary small talk.
        5. Do not invent information.
        6. Combine the existing summary with the new messages.
        7. Return only the updated summary.
        """

    summary_messages = [
        {
            "role": "system",
            "content": "You summarize conversations accurately."
        },
        {
            "role": "user",
            "content": summarization_prompt
        }
    ]

    updated_summary = generate_response(summary_messages)

    return updated_summary


def get_unsummarized_messages(conversation):

    last_summary_id = conversation.get(
        "summary_through_message_id"
    )

    query = {
        "conversation_id": conversation["_id"],
        "user_id": conversation["user_id"],
        "role": {"$in": ["user", "assistant"]},
        "is_deleted": False,
        "status": MessageStatus.COMPLETED.value
    }

    # If a previous summary exists, find its cursor message
    if last_summary_id:
        
        cursor_message = messages_db.find_one({
            "_id": last_summary_id,
            "conversation_id": conversation["_id"],
            "user_id": conversation["user_id"]
        })

        if not cursor_message:
            raise ValueError(
                "Summary cursor message not found"
            )

        cursor_date = cursor_message["createdAt"]
        cursor_id = cursor_message["_id"]

        query["$or"] = [
            {"createdAt": {"$gt": cursor_date}},
            {
                "createdAt": cursor_date,
                "_id": {"$gt": cursor_id}
            }
        ]

    unsummarized_messages = list(
        messages_db.find(query).sort([
            ("createdAt", 1),
            ("_id", 1)
        ])
    )

    return unsummarized_messages

def update_conversation_summary(conversation):

    # 1. Retrieve messages not yet summarized
    unsummarized_messages = get_unsummarized_messages(conversation)

    existing_summary = conversation.get("summary", "")

    # Nothing new to summarize
    if not unsummarized_messages:
        return existing_summary

    # 2. Check whether summarization is necessary
    unsummarized_tokens = count_message_tokens(unsummarized_messages)

    if unsummarized_tokens < SUMMARY_TRIGGER_TOKENS:
        return existing_summary

    # 3. Separate older messages from recent messages
    messages_for_summary = select_messages_for_summary(
        unsummarized_messages,
        RECENT_HISTORY_BUDGET
    )

    # No older messages are available for summarization
    if not messages_for_summary:
        return existing_summary

    # 4. Generate updated summary using Groq
    updated_summary = generate_conversation_summary(
        existing_summary=existing_summary,
        new_messages=messages_for_summary
    )

    if not updated_summary or not updated_summary.strip():
        raise ValueError("Generated summary is empty")

    # 5. Advance cursor only to the last summarized message
    last_message_id = messages_for_summary[-1]["_id"]

    # 6. Save summary and cursor atomically
    result = conversations_db.update_one(
        {
            "_id": conversation["_id"],
            "user_id": conversation["user_id"],
            "summary_through_message_id": conversation.get("summary_through_message_id")
        },
        {
            "$set": {
                "summary": updated_summary,
                "summary_through_message_id": last_message_id,
                "summary_updated_at": datetime.now(timezone.utc)
            }
        }
    )

    # 7. Detect concurrent updates
    if result.matched_count != 1:
        raise RuntimeError(
            "Conversation summary was modified by another request. "
            "Reload the conversation and retry."
        )

    return updated_summary