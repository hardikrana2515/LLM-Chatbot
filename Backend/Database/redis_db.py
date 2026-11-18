import redis
from datetime import datetime,timezone
from config.settings import settings

REDIS_URL = settings.redis_url.get_secret_value()

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