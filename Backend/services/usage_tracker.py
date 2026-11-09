
from datetime import datetime, timezone

from Database.db import llm_usage_db


def record_llm_usage(
    user_id,
    conversation_id,
    message_id,
    llm_result
):

    usage = llm_result.get("usage", {})
    timing = llm_result.get("timing", {})

    request_id = llm_result.get("request_id")

    usage_record = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "message_id": message_id,

        "model": llm_result.get("model"),

        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "reasoning_tokens": usage.get("reasoning_tokens", 0),

        "prompt_time": timing.get("prompt_time"),
        "completion_time": timing.get("completion_time"),
        "total_time": timing.get("total_time"),

        "request_id": request_id,

        "createdAt": datetime.now(timezone.utc)
    }

    # Prevent duplicate records for the same Groq request.
    if request_id:
        result = llm_usage_db.update_one(
            {"request_id": request_id},
            {"$setOnInsert": usage_record},
            upsert=True
        )

        return result.upserted_id

    result = llm_usage_db.insert_one(usage_record)

    return result.inserted_id
