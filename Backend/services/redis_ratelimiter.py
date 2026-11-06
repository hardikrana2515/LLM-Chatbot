
from fastapi import HTTPException, status
from redis.exceptions import RedisError

from Database.redis_db import redis_client


RATE_LIMIT = 5
WINDOW_SECONDS = 60


# Redis executes this script atomically.
RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])

if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end

local ttl = redis.call('TTL', KEYS[1])

return {count, ttl}
"""


def check_rate_limit(user_id: str, endpoint: str):

    key = f"rate_limit:user:{user_id}:{endpoint}"

    try:
        result = redis_client.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            WINDOW_SECONDS
        )

        request_count = int(result[0])
        ttl = int(result[1])

    except RedisError:
        # Fail closed: don't allow unprotected LLM requests
        # when Redis is unavailable.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting service is temporarily unavailable."
        )

    if request_count > RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(max(ttl, 1))}
        )

    return {
        "limit": RATE_LIMIT,
        "remaining": max(RATE_LIMIT - request_count, 0),
        "reset_in": max(ttl, 0)
    }
