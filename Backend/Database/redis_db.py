import redis
import os
from dotenv import load_dotenv
from datetime import datetime,timezone

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")

if not REDIS_URL:
    raise RuntimeError("REDIS_URL is missing from environment variables")

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses = True,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30
)

def check_redis_connection() :
    redis_client.ping()
    return {"status" : "connected",
            "time" :datetime.now(timezone.utc)}