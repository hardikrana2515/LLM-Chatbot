import tiktoken

encoding = tiktoken.get_encoding("o200k_harmony")

MAX_CONTEXT_BUDGET = 8000
SUMMARY_BUDGET = 1500
OUTPUT_RESERVE = 1000
SAFETY_MARGIN = 200
RECENT_HISTORY_BUDGET = 2500
SUMMARY_TRIGGER_TOKENS = 5000

def count_tokens(text: str) -> int:
    """
    Count approximate tokens in a text string.
    """
    return len(encoding.encode(text))

def count_message_tokens(messages: list) -> int:
    """
    Count approximate tokens in a list of chat messages.
    """
    total_tokens = 0

    for message in messages:
        total_tokens += count_tokens(message["role"])
        total_tokens += count_tokens(message["content"])

    return total_tokens

def select_recent_messages(messages: list, token_budget: int) -> list:

    selected_messages = []
    total_tokens = 0

    for message in reversed(messages):

        message_tokens = (
            count_tokens(message["role"]) + count_tokens(message["content"])
        )

        if total_tokens + message_tokens > token_budget:
            break

        selected_messages.append(message)
        total_tokens += message_tokens

    selected_messages.reverse()

    return selected_messages

def select_messages_for_summary(
    messages: list,
    recent_token_budget: int
) -> list:

    recent_messages = select_recent_messages(
        messages,
        recent_token_budget
    )

    recent_ids = {
        message["_id"] for message in recent_messages
    }

    summary_messages = [
        message for message in messages if message["_id"] not in recent_ids
    ]

    return summary_messages


def calculate_history_budget(
    system_prompt: str,
    summary: str,
    user_message: str
) -> int:

    system_tokens = count_tokens(system_prompt)
    user_tokens = count_tokens(user_message)

    summary_content = f"Conversation summary: {summary}" if summary else ""
    summary_tokens = count_tokens(summary_content)

    available_tokens = (
        MAX_CONTEXT_BUDGET
        - system_tokens
        - summary_tokens
        - user_tokens
        - OUTPUT_RESERVE
        - SAFETY_MARGIN
    )

    if available_tokens < 0:
        raise ValueError(
            "Request is too large. Please shorten your message."
        )

    return available_tokens

def build_chat_context(
    system_prompt: str,
    summary: str,
    conversation_history: list,
    current_user_message: str
) -> list:

    history_budget = calculate_history_budget(
        system_prompt,
        summary,
        current_user_message
    )

    selected_history = select_recent_messages(
        conversation_history,
        history_budget
    )

    final_messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    if summary:
        final_messages.append({
            "role": "system",
            "content": f"Conversation summary: {summary}"
        })

    for message in selected_history:
        final_messages.append({
            "role": message["role"],
            "content": message["content"]
        })


    final_messages.append({
        "role": "user",
        "content": current_user_message
    })

    return final_messages