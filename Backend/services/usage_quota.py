import math

from datetime import datetime, timezone, timedelta
import uuid
from fastapi import HTTPException, status

from Database.redis_db import redis_client
from config.usage_limits import USAGE_LIMITS


RESERVE_TOKENS_SCRIPT = """
local daily_key = KEYS[1]
local monthly_key = KEYS[2]
local reservation_key = KEYS[3]

local requested = tonumber(ARGV[1])
local daily_limit = tonumber(ARGV[2])
local monthly_limit = tonumber(ARGV[3])
local daily_ttl = tonumber(ARGV[4])
local monthly_ttl = tonumber(ARGV[5])

local daily_used = tonumber(redis.call('GET', daily_key) or '0')
local monthly_used = tonumber(redis.call('GET', monthly_key) or '0')

-- Check both limits before reserving anything.
if daily_used + requested > daily_limit then
    return {0, daily_used, monthly_used, 1}
end

if monthly_used + requested > monthly_limit then
    return {0, daily_used, monthly_used, 2}
end

-- Reserve tokens atomically.
daily_used = redis.call('INCRBY', daily_key, requested)
monthly_used = redis.call('INCRBY', monthly_key, requested)

-- Set expiry only if the counter does not already have an expiry.
if redis.call('TTL', daily_key) == -1 then
    redis.call('EXPIRE', daily_key, daily_ttl)
end

if redis.call('TTL', monthly_key) == -1 then
    redis.call('EXPIRE', monthly_key, monthly_ttl)
end

-- Store reservation metadata for later reconciliation.
redis.call(
    'HSET',
    reservation_key,
    'reservation_id', ARGV[6],
    'requested_tokens', requested,
    'daily_key', daily_key,
    'monthly_key', monthly_key,
    'status', 'reserved',
    'created_at', ARGV[7]
)
return {1, daily_used, monthly_used, 0}
"""


RECONCILE_TOKENS_SCRIPT = """
local reservation_key = KEYS[1]
local daily_key = KEYS[2]
local monthly_key = KEYS[3]

local actual_tokens = tonumber(ARGV[1])
local daily_limit = tonumber(ARGV[2])
local monthly_limit = tonumber(ARGV[3])
local reconciled_at = ARGV[4]

-- Check whether the reservation exists.
if redis.call('EXISTS', reservation_key) == 0 then
    return {-1, 0, 0, 0, 0, 0}
end

local reservation_status = redis.call(
    'HGET', reservation_key, 'status'
)

-- Prevent duplicate reconciliation.
if reservation_status ~= 'reserved' then
    return {2, 0, 0, 0, 0, 0}
end

local reserved_tokens = tonumber(
    redis.call('HGET', reservation_key, 'requested_tokens')
)

-- Verify that the supplied counter keys belong to this reservation.
local stored_daily_key = redis.call(
    'HGET', reservation_key, 'daily_key'
)

local stored_monthly_key = redis.call(
    'HGET', reservation_key, 'monthly_key'
)

if stored_daily_key ~= daily_key or stored_monthly_key ~= monthly_key then
    return {-2, 0, 0, 0, 0, 0}
end

-- Calculate the difference between actual and reserved usage.
local adjustment = actual_tokens - reserved_tokens

local daily_used = 0
local monthly_used = 0

-- Adjust only counters that still exist.
if redis.call('EXISTS', daily_key) == 1 then
    daily_used = redis.call('INCRBY', daily_key, adjustment)
end

if redis.call('EXISTS', monthly_key) == 1 then
    monthly_used = redis.call('INCRBY', monthly_key, adjustment)
end

-- Mark reservation as reconciled.
redis.call(
    'HSET',
    reservation_key,
    'status', 'reconciled',
    'actual_tokens', actual_tokens,
    'adjustment', adjustment,
    'reconciled_at', reconciled_at
)

return {
    1,
    daily_used,
    monthly_used,
    adjustment,
    daily_used > daily_limit and 1 or 0,
    monthly_used > monthly_limit and 1 or 0
}
"""

RELEASE_TOKENS_SCRIPT = """
local reservation_key = KEYS[1]
local daily_key = KEYS[2]
local monthly_key = KEYS[3]

local released_at = ARGV[1]

-- Check whether reservation exists
if redis.call('EXISTS', reservation_key) == 0 then
    return {-1, 0, 0, 0}
end

-- Only reserved tokens can be released
local reservation_status = redis.call(
    'HGET', reservation_key, 'status'
)

if reservation_status ~= 'reserved' then
    return {2, 0, 0, 0}
end

local reserved_tokens = tonumber(
    redis.call('HGET', reservation_key, 'requested_tokens')
)

local stored_daily_key = redis.call(
    'HGET', reservation_key, 'daily_key'
)

local stored_monthly_key = redis.call(
    'HGET', reservation_key, 'monthly_key'
)

-- Verify counter keys
if stored_daily_key ~= daily_key or stored_monthly_key ~= monthly_key then
    return {-2, 0, 0, 0}
end

local daily_used = 0
local monthly_used = 0

-- Release daily reserved tokens
if redis.call('EXISTS', daily_key) == 1 then
    daily_used = redis.call('INCRBY', daily_key, -reserved_tokens)
end

-- Release monthly reserved tokens
if redis.call('EXISTS', monthly_key) == 1 then
    monthly_used = redis.call('INCRBY', monthly_key, -reserved_tokens)
end

-- Update reservation status
redis.call(
    'HSET',
    reservation_key,
    'status', 'released',
    'released_at', released_at
)

return {1, daily_used, monthly_used, reserved_tokens}
"""

def reserve_tokens(user_id: str, requested_tokens: int):
    # Validate requested token amount.
    if (
        isinstance(requested_tokens, bool)
        or not isinstance(requested_tokens, int)
        or requested_tokens <= 0
    ):
        raise ValueError("requested_tokens must be a positive integer")

    now = datetime.now(timezone.utc)

    # Calculate next UTC midnight.
    next_day = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    ) + timedelta(days=1) 
    next_day = next_day + timedelta(days=1)

    # Calculate first day of next month.
    if now.month == 12:
        next_month = now.replace(
            year=now.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )
    else:
        next_month = now.replace(
            month=now.month + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

    daily_ttl = math.ceil((next_day - now).total_seconds())
    monthly_ttl = math.ceil((next_month - now).total_seconds())

    # Create period-specific Redis keys.
    daily_key = f"usage:{{{user_id}}}:daily:{now:%Y-%m-%d}"
    monthly_key = f"usage:{{{user_id}}}:monthly:{now:%Y-%m}"

    reservation_id = uuid.uuid4().hex

    reservation_key = (
        f"usage:{{{user_id}}}:reservation:{reservation_id}"
    )

    try:
        result = redis_client.eval(
            RESERVE_TOKENS_SCRIPT,
            3,
            daily_key,
            monthly_key,
            reservation_key,
            requested_tokens,
            USAGE_LIMITS["daily_tokens"],
            USAGE_LIMITS["monthly_tokens"],
            daily_ttl,
            monthly_ttl,
            reservation_id,
            int(now.timestamp())
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage quota service is temporarily unavailable."
        ) from exc

    allowed = int(result[0])
    daily_used = int(result[1])
    monthly_used = int(result[2])
    reason = int(result[3])

    # Reservation rejected.
    if not allowed:
        if reason == 1:
            message = "Daily token quota exceeded."
            quota_type = "daily"
            limit = USAGE_LIMITS["daily_tokens"]
            used = daily_used
        else:
            message = "Monthly token quota exceeded."
            quota_type = "monthly"
            limit = USAGE_LIMITS["monthly_tokens"]
            used = monthly_used

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": message,
                "quota_type": quota_type,
                "used_tokens": used,
                "limit_tokens": limit,
                "requested_tokens": requested_tokens
            }
        )

    # Reservation successful.
    return {
        "reservation_id": reservation_id,
        "reserved_tokens": requested_tokens,
        "daily_used": daily_used,
        "monthly_used": monthly_used,
        "daily_remaining": (
            USAGE_LIMITS["daily_tokens"] - daily_used
        ),
        "monthly_remaining": (
            USAGE_LIMITS["monthly_tokens"] - monthly_used
        )
    }


def reconcile_tokens(
    user_id: str,
    reservation_id: str,
    actual_tokens: int
):
    if (
        isinstance(actual_tokens, bool)
        or not isinstance(actual_tokens, int)
        or actual_tokens < 0
    ):
        raise ValueError("actual_tokens must be a non-negative integer")

    reservation_key = (
        f"usage:{{{user_id}}}:reservation:{reservation_id}"
    )

    try:
        # Retrieve the counter keys stored during reservation.
        metadata = redis_client.hgetall(reservation_key)

        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token reservation not found."
            )

        daily_key = metadata["daily_key"]
        monthly_key = metadata["monthly_key"]

        result = redis_client.eval(
            RECONCILE_TOKENS_SCRIPT,
            3,
            reservation_key,
            daily_key,
            monthly_key,
            actual_tokens,
            USAGE_LIMITS["daily_tokens"],
            USAGE_LIMITS["monthly_tokens"],
            int(datetime.now(timezone.utc).timestamp())
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reconcile token usage."
        ) from exc

    result_code = int(result[0])

    if result_code == -1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token reservation not found."
        )

    if result_code == -2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reservation counter keys do not match."
        )

    if result_code == 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Token reservation has already been reconciled."
        )

    daily_used = int(result[1])
    monthly_used = int(result[2])
    adjustment = int(result[3])

    return {
        "status": "reconciled",
        "reserved_tokens": int(metadata["requested_tokens"]),
        "actual_tokens": actual_tokens,
        "adjustment": adjustment,
        "daily_used": daily_used,
        "monthly_used": monthly_used,
        "daily_over_limit": bool(result[4]),
        "monthly_over_limit": bool(result[5])
    }

def release_tokens(user_id: str, reservation_id: str):

    reservation_key = (
        f"usage:{{{user_id}}}:reservation:{reservation_id}"
    )

    try:
        metadata = redis_client.hgetall(reservation_key)

        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token reservation not found."
            )

        daily_key = metadata["daily_key"]
        monthly_key = metadata["monthly_key"]

        result = redis_client.eval(
            RELEASE_TOKENS_SCRIPT,
            3,
            reservation_key,
            daily_key,
            monthly_key,
            int(datetime.now(timezone.utc).timestamp())
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to release token reservation."
        ) from exc

    result_code = int(result[0])

    if result_code == -1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token reservation not found."
        )

    if result_code == -2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reservation counter keys do not match."
        )

    if result_code == 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Token reservation is already finalized."
        )

    return {
        "status": "released",
        "released_tokens": int(result[3]),
        "daily_used": int(result[1]),
        "monthly_used": int(result[2])
    }

