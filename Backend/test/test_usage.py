
import uuid
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from services.usage_quota import reserve_tokens,reconcile_tokens
from config.usage_limits import USAGE_LIMITS
from Database.redis_db import redis_client

def cleanup_user(user_id):
    now = datetime.now(timezone.utc)

    redis_client.delete(
        f"usage:{{{user_id}}}:daily:{now:%Y-%m-%d}",
        f"usage:{{{user_id}}}:monthly:{now:%Y-%m}"
    )

    keys = redis_client.keys(
        f"usage:{{{user_id}}}:reservation:*"
    )

    if keys:
        redis_client.delete(*keys)

def test_token_reservation_success(monkeypatch):
    user_id = f"test_{uuid.uuid4().hex}"

    monkeypatch.setitem(USAGE_LIMITS, "daily_tokens", 1000)
    monkeypatch.setitem(USAGE_LIMITS, "monthly_tokens", 5000)

    try:
        result = reserve_tokens(user_id, 100)

        assert result["reserved_tokens"] == 100
        assert result["daily_used"] == 100
        assert result["monthly_used"] == 100
        assert result["daily_remaining"] == 900
        assert result["monthly_remaining"] == 4900
    finally:
        cleanup_user(user_id)


def test_daily_quota_exceeded(monkeypatch):
    user_id = f"test_{uuid.uuid4().hex}"

    monkeypatch.setitem(USAGE_LIMITS, "daily_tokens", 100)
    monkeypatch.setitem(USAGE_LIMITS, "monthly_tokens", 5000)

    try:
        reserve_tokens(user_id, 80)

        with pytest.raises(HTTPException) as exc:
            reserve_tokens(user_id, 30)

        assert exc.value.status_code == 429
        assert exc.value.detail["quota_type"] == "daily"
    finally:
        cleanup_user(user_id)


def test_monthly_quota_exceeded(monkeypatch):
    user_id = f"test_{uuid.uuid4().hex}"

    monkeypatch.setitem(USAGE_LIMITS, "daily_tokens", 5000)
    monkeypatch.setitem(USAGE_LIMITS, "monthly_tokens", 100)

    try:
        reserve_tokens(user_id, 80)

        with pytest.raises(HTTPException) as exc:
            reserve_tokens(user_id, 30)

        assert exc.value.status_code == 429
        assert exc.value.detail["quota_type"] == "monthly"
    finally:
        cleanup_user(user_id)


def test_invalid_token_reservation():
    with pytest.raises(ValueError):
        reserve_tokens("test_user", 0)

    with pytest.raises(ValueError):
        reserve_tokens("test_user", -10)


def test_reservation_metadata_saved():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        result = reserve_tokens(user_id, 250)
        reservation_id = result["reservation_id"]

        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )

        metadata = redis_client.hgetall(reservation_key)

        assert metadata["reservation_id"] == reservation_id
        assert int(metadata["requested_tokens"]) == 250
        assert metadata["status"] == "reserved"
    finally:
        cleanup_user(user_id)


def test_reconcile_releases_unused_tokens():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)

        result = reconcile_tokens(
            user_id,
            reservation["reservation_id"],
            650
        )

        assert result["status"] == "reconciled"
        assert result["reserved_tokens"] == 1000
        assert result["actual_tokens"] == 650
        assert result["adjustment"] == -350
        assert result["daily_used"] == 650
        assert result["monthly_used"] == 650

    finally:
        cleanup_user(user_id)


def test_reconcile_exact_usage():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 500)

        result = reconcile_tokens(
            user_id,
            reservation["reservation_id"],
            500
        )

        assert result["adjustment"] == 0
        assert result["daily_used"] == 500
        assert result["monthly_used"] == 500

    finally:
        cleanup_user(user_id)


def test_duplicate_reconciliation_rejected():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        reconcile_tokens(user_id, reservation_id, 700)

        with pytest.raises(HTTPException) as exc:
            reconcile_tokens(user_id, reservation_id, 700)

        assert exc.value.status_code == 409

    finally:
        cleanup_user(user_id)


def test_actual_usage_exceeds_reservation():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 500)

        result = reconcile_tokens(
            user_id,
            reservation["reservation_id"],
            700
        )

        assert result["adjustment"] == 200
        assert result["daily_used"] == 700
        assert result["monthly_used"] == 700

    finally:
        cleanup_user(user_id)
