from services.token_manager import build_chat_context
from services.summarizer import (generate_conversation_summary,get_unsummarized_messages)

system_prompt = "You are a helpful AI assistant."

summary = generate_conversation_summary(
    existing_summary="The user is learning about Python programming.",
    new_messages=[
        {"role": "user", "content": "Why is Python popular?"},
        {"role": "assistant", "content": "Python is popular due to its simplicity and readability."}
    ]
)

conversation = {
    "_id": "conversation_123",
    "user_id": "user_456",
    "summary_through_message_id": "message_789"
}
unsummarized_messages = get_unsummarized_messages(conversation)

print("Unsummarized Messages:" , unsummarized_messages)
print("")
print("Existing Summary:" , summary)
print("")

conversation_history = [
    {"role": "user", "content": "What is Python?"},
    {"role": "assistant", "content": "Python is a programming language."},
    {"role": "user", "content": "What are functions?"},
    {"role": "assistant", "content": "Functions are reusable blocks of code."}
]

current_user_message = "Explain Python decorators."

final_messages = build_chat_context(
    system_prompt,
    summary,
    conversation_history,
    current_user_message
)

for message in final_messages:
    print(message)
