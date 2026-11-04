from llm import generate_response
from Database.db import messages_db
from Model.schema import MessageStatus


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

    if last_summary_id:
        last_summary_message = messages_db.find_one({
            "_id": last_summary_id,
            "conversation_id": conversation["_id"]
        })

        if not last_summary_message:
            raise ValueError("Summary cursor message not found")

        query["createdAt"] = {
            "$gt": last_summary_message["createdAt"]
        }

    return list(
        messages_db.find(query).sort([
            ("createdAt", 1),
            ("_id", 1)
        ])
    )