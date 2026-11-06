from groq import Groq,APIConnectionError,APITimeoutError,RateLimitError,APIStatusError
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("GROQ_MODEL")

if not api_key:
    raise RuntimeError("GROQ_API_KEY is missing")

if not MODEL_NAME:
    raise RuntimeError("GROQ_MODEL is missing")

client = Groq(api_key=api_key,
              timeout=30,
              max_retries=2)




def generate_response(chat_history):
        
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=chat_history
        )

        assistant_response = completion.choices[0].message.content

        return assistant_response


    