
import math

from fastapi import HTTPException, status
from redis.exceptions import RedisError

from Database.redis_db import redis_client
from config.config import RATE_LIMITS


TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]

local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])

-- Use Redis server time to avoid application clock differences.
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000

-- Retrieve the existing bucket state.
local values = redis.call('HMGET', key, 'tokens', 'last_refill')

local tokens = tonumber(values[1])
local last_refill = tonumber(values[2])

-- Initialize a new bucket.
if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- Refill tokens based on elapsed time.
local elapsed = math.max(0, now - last_refill)

tokens = math.min(
    capacity,
    tokens + (elapsed * refill_rate)
)

-- Consume one token if available.
local allowed = 0
local retry_after = 0

if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_after = (1 - tokens) / refill_rate
end

-- Save updated bucket state.
redis.call(
    'HSET',
    key,
    'tokens', string.format('%.6f', tokens),
    'last_refill', string.format('%.6f', now)
)

-- Remove inactive buckets automatically.
local ttl = math.ceil((capacity / refill_rate) * 2)
redis.call('EXPIRE', key, ttl)

return {
    allowed,
    tokens,
    retry_after
}
"""


def check_rate_limit(identifier: str, endpoint: str):

    config = RATE_LIMITS.get(endpoint)

    if not config:
        raise ValueError(
            f"Rate limit configuration missing: {endpoint}"
        )

    capacity = config["capacity"]
    refill_rate = config["refill_rate"]

    if capacity <= 0 or refill_rate <= 0:
        raise ValueError("Invalid rate limit configuration")

    key = f"rate_limit:{endpoint}:{identifier}"

    try:
        result = redis_client.eval(
            TOKEN_BUCKET_SCRIPT,
            1,
            key,
            capacity,
            refill_rate
        )

        allowed = int(result[0])
        remaining_tokens = float(result[1])
        retry_after = float(result[2])

    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting service is unavailable."
        )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={
                "Retry-After": str(max(1, math.ceil(retry_after)))
            }
        )

    return {
        "limit": capacity,
        "remaining": math.floor(remaining_tokens),
        "reset_in": math.ceil(
            (capacity - remaining_tokens) / refill_rate
        )
    }
