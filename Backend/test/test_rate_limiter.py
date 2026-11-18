
import time
import uuid

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from services import redis_ratelimiter as limiter


@pytest.fixture
def test_identifier():
    return f"pytest-{uuid.uuid4().hex}"


def configure_test_limit(monkeypatch, endpoint, capacity, refill_rate):
    monkeypatch.setitem(
        limiter.RATE_LIMITS,
        endpoint,
        {
            "capacity": capacity,
            "refill_rate": refill_rate
        }
    )


def test_bucket_allows_requests(monkeypatch, test_identifier):

    endpoint = "test_allow"

    configure_test_limit(monkeypatch, endpoint, 3, 1)

    key = f"rate_limit:{endpoint}:{test_identifier}"

    try:
        for _ in range(3):
            result = limiter.check_rate_limit(
                identifier=test_identifier,
                endpoint=endpoint
            )

            assert result["remaining"] >= 0

    finally:
        limiter.redis_client.delete(key)


def test_bucket_blocks_excess_requests(monkeypatch, test_identifier):

    endpoint = "test_block"

    configure_test_limit(monkeypatch, endpoint, 2, 1)

    key = f"rate_limit:{endpoint}:{test_identifier}"

    try:
        limiter.check_rate_limit(test_identifier, endpoint)
        limiter.check_rate_limit(test_identifier, endpoint)

        with pytest.raises(HTTPException) as exc:

            limiter.check_rate_limit(test_identifier, endpoint)

        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers

    finally:
        limiter.redis_client.delete(key)


def test_bucket_refills_tokens(monkeypatch, test_identifier):

    endpoint = "test_refill"

    configure_test_limit(monkeypatch, endpoint, 2, 2)

    key = f"rate_limit:{endpoint}:{test_identifier}"

    try:
        limiter.check_rate_limit(test_identifier, endpoint)
        limiter.check_rate_limit(test_identifier, endpoint)

        with pytest.raises(HTTPException):
            limiter.check_rate_limit(test_identifier, endpoint)

        time.sleep(0.6)

        result = limiter.check_rate_limit(
            test_identifier,
            endpoint
        )

        assert result["remaining"] >= 0

    finally:
        limiter.redis_client.delete(key)


def test_users_have_independent_buckets(monkeypatch, test_identifier):

    endpoint = "test_users"

    configure_test_limit(monkeypatch, endpoint, 1, 1)

    user_a = f"{test_identifier}-A"
    user_b = f"{test_identifier}-B"

    keys = [
        f"rate_limit:{endpoint}:{user_a}",
        f"rate_limit:{endpoint}:{user_b}"
    ]

    try:
        limiter.check_rate_limit(user_a, endpoint)

        with pytest.raises(HTTPException):
            limiter.check_rate_limit(user_a, endpoint)

        result = limiter.check_rate_limit(user_b, endpoint)

        assert result["remaining"] >= 0

    finally:
        limiter.redis_client.delete(*keys)


def test_different_endpoints_have_independent_buckets(
    monkeypatch,
    test_identifier
):

    configure_test_limit(monkeypatch, "test_endpoint_a", 1, 1)
    configure_test_limit(monkeypatch, "test_endpoint_b", 1, 1)

    keys = [
        f"rate_limit:test_endpoint_a:{test_identifier}",
        f"rate_limit:test_endpoint_b:{test_identifier}"
    ]

    try:
        limiter.check_rate_limit(test_identifier, "test_endpoint_a")

        with pytest.raises(HTTPException):
            limiter.check_rate_limit(
                test_identifier,
                "test_endpoint_a"
            )

        result = limiter.check_rate_limit(
            test_identifier,
            "test_endpoint_b"
        )

        assert result["remaining"] >= 0

    finally:
        limiter.redis_client.delete(*keys)


def test_redis_failure_returns_503(monkeypatch, test_identifier):

    def simulate_redis_failure(*args, **kwargs):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(
        limiter.redis_client,
        "eval",
        simulate_redis_failure
    )

    with pytest.raises(HTTPException) as exc:

        limiter.check_rate_limit(
            test_identifier,
            "create_message"
        )

    assert exc.value.status_code == 503
