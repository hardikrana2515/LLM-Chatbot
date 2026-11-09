
from groq import Groq
import os
from dotenv import load_dotenv
from config.usage_limits import USAGE_LIMITS

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("GROQ_MODEL")

if not api_key:
    raise RuntimeError("GROQ_API_KEY is missing")

if not MODEL_NAME:
    raise RuntimeError("GROQ_MODEL is missing")

client = Groq(
    api_key=api_key,
    timeout=30,
    max_retries=2
)


def generate_response(chat_history):

    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=chat_history,
        max_completion_tokens=USAGE_LIMITS["max_output_tokens"]
    )

    assistant_response = completion.choices[0].message.content

    usage = completion.usage

    return {
        "content": assistant_response,

        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "reasoning_tokens": (
                usage.completion_tokens_details.reasoning_tokens
                if usage and usage.completion_tokens_details
                else 0
            )
        },

        "model": completion.model,
        "request_id": completion.id,
        "finish_reason": completion.choices[0].finish_reason,
        "timing": {
            "prompt_time": usage.prompt_time if usage else None,
            "completion_time": usage.completion_time if usage else None,
            "total_time": usage.total_time if usage else None
        }
    }
