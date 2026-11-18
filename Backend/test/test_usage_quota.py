
import uuid
from datetime import datetime, timezone,timedelta
import pytest
from fastapi import HTTPException
from concurrent.futures import ThreadPoolExecutor
from services.usage_quota import (reserve_tokens, reconcile_tokens ,release_tokens,cleanup_expired_reservations)
from config.usage_limits import USAGE_LIMITS
from Database.redis_db import redis_client



def cleanup_user(user_id):
    now = datetime.now(timezone.utc)

    redis_client.delete(
        f"usage:{{{user_id}}}:daily:{now:%Y-%m-%d}",
        f"usage:{{{user_id}}}:monthly:{now:%Y-%m}",
        f"usage:{{{user_id}}}:reservations:expiry"
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
        redis_client.delete(
            f"usage:{{{user_id}}}:daily:{__import__('datetime').datetime.now(__import__('datetime').timezone.utc):%Y-%m-%d}",
            f"usage:{{{user_id}}}:monthly:{__import__('datetime').datetime.now(__import__('datetime').timezone.utc):%Y-%m}"
        )


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
        now = __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc
        )
        redis_client.delete(
            f"usage:{{{user_id}}}:daily:{now:%Y-%m-%d}",
            f"usage:{{{user_id}}}:monthly:{now:%Y-%m}"
        )


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
        now = __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc
        )
        redis_client.delete(
            f"usage:{{{user_id}}}:daily:{now:%Y-%m-%d}",
            f"usage:{{{user_id}}}:monthly:{now:%Y-%m}"
        )


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


def test_reconcile_releases_unused_tokens():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)

        result = reconcile_tokens(
            user_id, reservation["reservation_id"], 650
        )

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
            user_id, reservation["reservation_id"], 500
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
            user_id, reservation["reservation_id"], 700
        )

        assert result["adjustment"] == 200
        assert result["daily_used"] == 700
        assert result["monthly_used"] == 700

    finally:
        cleanup_user(user_id)


def test_release_reservation_success():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)

        result = release_tokens(
            user_id,
            reservation["reservation_id"]
        )

        assert result["status"] == "released"
        assert result["released_tokens"] == 1000
        assert result["daily_used"] == 0
        assert result["monthly_used"] == 0

    finally:
        cleanup_user(user_id)

def test_duplicate_release_rejected():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        release_tokens(user_id, reservation_id)

        with pytest.raises(HTTPException) as exc:
            release_tokens(user_id, reservation_id)

        assert exc.value.status_code == 409

    finally:
        cleanup_user(user_id)

def test_reconciled_reservation_cannot_be_released():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        reconcile_tokens(user_id, reservation_id, 700)

        with pytest.raises(HTTPException) as exc:
            release_tokens(user_id, reservation_id)

        assert exc.value.status_code == 409

    finally:
        cleanup_user(user_id)

def test_expired_reservation_releases_tokens():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )

        expiry_index_key = (
            f"usage:{{{user_id}}}:reservations:expiry"
        )

        now = int(datetime.now(timezone.utc).timestamp())
        expired_at = now - 60

        # Simulate an expired reservation.
        redis_client.hset(
            reservation_key,
            "expires_at",
            expired_at
        )

        redis_client.zadd(
            expiry_index_key,
            {reservation_id: expired_at}
        )

        # Verify tokens are initially reserved.
        assert int(
            redis_client.get(
                f"usage:{{{user_id}}}:daily:{datetime.now(timezone.utc):%Y-%m-%d}"
            )
        ) == 1000

        # Run crash recovery.
        cleaned = cleanup_expired_reservations(user_id)

        assert cleaned == 1

        # Verify both counters are released.
        assert int(
            redis_client.get(
                f"usage:{{{user_id}}}:daily:{datetime.now(timezone.utc):%Y-%m-%d}"
            )
        ) == 0

        assert int(
            redis_client.get(
                f"usage:{{{user_id}}}:monthly:{datetime.now(timezone.utc):%Y-%m}"
            )
        ) == 0

        # Verify reservation status.
        metadata = redis_client.hgetall(reservation_key)

        assert metadata["status"] == "expired"

        # Verify removal from expiration index.
        assert redis_client.zscore(
            expiry_index_key,
            reservation_id
        ) is None

    finally:
        cleanup_user(user_id)


def test_active_reservation_is_not_cleaned():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )

        expiry_index_key = (
            f"usage:{{{user_id}}}:reservations:expiry"
        )

        cleaned = cleanup_expired_reservations(user_id)

        assert cleaned == 0

        metadata = redis_client.hgetall(reservation_key)
        assert metadata["status"] == "reserved"

        assert redis_client.zscore(
            expiry_index_key, reservation_id
        ) is not None

        daily_key = (
            f"usage:{{{user_id}}}:daily:"
            f"{datetime.now(timezone.utc):%Y-%m-%d}"
        )

        assert int(redis_client.get(daily_key)) == 1000

    finally:
        cleanup_user(user_id)

def test_cleanup_removes_missing_reservation_metadata():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        expiry_index_key = (
            f"usage:{{{user_id}}}:reservations:expiry"
        )

        reservation_id = uuid.uuid4().hex
        now = int(datetime.now(timezone.utc).timestamp())

        # Add an expired ID to the index without creating its hash.
        redis_client.zadd(
            expiry_index_key,
            {reservation_id: now - 60}
        )

        cleaned = cleanup_expired_reservations(user_id)

        assert cleaned == 0

        # Orphaned index entry should be removed.
        assert redis_client.zscore(
            expiry_index_key, reservation_id
        ) is None

    finally:
        cleanup_user(user_id)

def test_expired_reservation_is_cleaned_only_once():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )
        expiry_index_key = (
            f"usage:{{{user_id}}}:reservations:expiry"
        )

        now = int(datetime.now(timezone.utc).timestamp())
        expired_at = now - 60

        redis_client.hset(
            reservation_key, "expires_at", expired_at
        )
        redis_client.zadd(
            expiry_index_key, {reservation_id: expired_at}
        )

        first_cleanup = cleanup_expired_reservations(user_id)
        second_cleanup = cleanup_expired_reservations(user_id)

        assert first_cleanup == 1
        assert second_cleanup == 0

        daily_key = (
            f"usage:{{{user_id}}}:daily:"
            f"{datetime.now(timezone.utc):%Y-%m-%d}"
        )
        monthly_key = (
            f"usage:{{{user_id}}}:monthly:"
            f"{datetime.now(timezone.utc):%Y-%m}"
        )

        assert int(redis_client.get(daily_key)) == 0
        assert int(redis_client.get(monthly_key)) == 0

        metadata = redis_client.hgetall(reservation_key)
        assert metadata["status"] == "expired"

    finally:
        cleanup_user(user_id)


def test_multiple_expired_reservations_are_cleaned():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        first = reserve_tokens(user_id, 1000)
        second = reserve_tokens(user_id, 2000)

        now = int(datetime.now(timezone.utc).timestamp())
        expired_at = now - 60

        for reservation in (first, second):
            reservation_id = reservation["reservation_id"]
            reservation_key = (
                f"usage:{{{user_id}}}:reservation:{reservation_id}"
            )
            redis_client.hset(
                reservation_key, "expires_at", expired_at
            )
            redis_client.zadd(
                f"usage:{{{user_id}}}:reservations:expiry",
                {reservation_id: expired_at}
            )

        cleaned = cleanup_expired_reservations(user_id)

        assert cleaned == 2

        daily_key = (
            f"usage:{{{user_id}}}:daily:"
            f"{datetime.now(timezone.utc):%Y-%m-%d}"
        )
        monthly_key = (
            f"usage:{{{user_id}}}:monthly:"
            f"{datetime.now(timezone.utc):%Y-%m}"
        )

        assert int(redis_client.get(daily_key)) == 0
        assert int(redis_client.get(monthly_key)) == 0

    finally:
        cleanup_user(user_id)

def test_reservation_reconciled_after_midnight():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        # Simulate the previous day and current day.
        previous_day = datetime(2026, 11, 8, 23, 59, 0, tzinfo=timezone.utc)
        current_day = previous_day + timedelta(days=1)

        old_daily_key = (
            f"usage:{{{user_id}}}:daily:{previous_day:%Y-%m-%d}"
        )
        new_daily_key = (
            f"usage:{{{user_id}}}:daily:{current_day:%Y-%m-%d}"
        )
        monthly_key = (
            f"usage:{{{user_id}}}:monthly:{previous_day:%Y-%m}"
        )

        reservation_id = uuid.uuid4().hex
        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )
        expiry_index_key = (
            f"usage:{{{user_id}}}:reservations:expiry"
        )

        # Simulate a reservation created before midnight.
        redis_client.set(old_daily_key, 1000)
        redis_client.set(monthly_key, 1000)

        redis_client.hset(
            reservation_key,
            mapping={
                "reservation_id": reservation_id,
                "requested_tokens": 1000,
                "daily_key": old_daily_key,
                "monthly_key": monthly_key,
                "status": "reserved",
                "created_at": int(previous_day.timestamp()),
                "expires_at": int(
                    (previous_day + timedelta(minutes=10)).timestamp()
                )
            }
        )

        redis_client.zadd(
            expiry_index_key,
            {reservation_id: int(
                (previous_day + timedelta(minutes=10)).timestamp()
            )}
        )

        # Reconcile after midnight.
        result = reconcile_tokens(user_id, reservation_id, 650)

        assert result["daily_used"] == 650
        assert result["monthly_used"] == 650

        # Previous day's counter must be updated.
        assert int(redis_client.get(old_daily_key)) == 650

        # New day's counter must remain untouched.
        assert redis_client.get(new_daily_key) is None

        assert int(redis_client.get(monthly_key)) == 650

    finally:
        cleanup_user(user_id)
        redis_client.delete(
            f"usage:{{{user_id}}}:daily:2026-11-08",
            f"usage:{{{user_id}}}:daily:2026-11-09",
            f"usage:{{{user_id}}}:monthly:2026-11"
        )

def test_reservation_reconciled_after_month_change():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        previous_month = datetime(
            2026, 10, 31, 23, 59, 0, tzinfo=timezone.utc
        )
        current_month = datetime(
            2026, 11, 1, 0, 1, 0, tzinfo=timezone.utc
        )

        daily_key = (
            f"usage:{{{user_id}}}:daily:{previous_month:%Y-%m-%d}"
        )
        old_monthly_key = (
            f"usage:{{{user_id}}}:monthly:{previous_month:%Y-%m}"
        )
        new_monthly_key = (
            f"usage:{{{user_id}}}:monthly:{current_month:%Y-%m}"
        )

        reservation_id = uuid.uuid4().hex
        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )

        redis_client.set(daily_key, 1000)
        redis_client.set(old_monthly_key, 1000)

        redis_client.hset(
            reservation_key,
            mapping={
                "reservation_id": reservation_id,
                "requested_tokens": 1000,
                "daily_key": daily_key,
                "monthly_key": old_monthly_key,
                "status": "reserved",
                "created_at": int(previous_month.timestamp()),
                "expires_at": int(
                    (previous_month + timedelta(minutes=10)).timestamp()
                )
            }
        )

        redis_client.zadd(
            f"usage:{{{user_id}}}:reservations:expiry",
            {
                reservation_id: int(
                    (previous_month + timedelta(minutes=10)).timestamp()
                )
            }
        )

        result = reconcile_tokens(user_id, reservation_id, 650)

        assert result["daily_used"] == 650
        assert result["monthly_used"] == 650

        assert int(redis_client.get(daily_key)) == 650
        assert int(redis_client.get(old_monthly_key)) == 650

        # November's quota must remain untouched.
        assert redis_client.get(new_monthly_key) is None

    finally:
        cleanup_user(user_id)
        redis_client.delete(
            f"usage:{{{user_id}}}:daily:2026-10-31",
            f"usage:{{{user_id}}}:monthly:2026-10",
            f"usage:{{{user_id}}}:monthly:2026-11"
        )

def test_reservation_released_after_midnight():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        previous_day = datetime(
            2026, 11, 8, 23, 59, 0, tzinfo=timezone.utc
        )
        current_day = previous_day + timedelta(days=1)

        old_daily_key = (
            f"usage:{{{user_id}}}:daily:{previous_day:%Y-%m-%d}"
        )
        new_daily_key = (
            f"usage:{{{user_id}}}:daily:{current_day:%Y-%m-%d}"
        )
        monthly_key = (
            f"usage:{{{user_id}}}:monthly:{previous_day:%Y-%m}"
        )

        reservation_id = uuid.uuid4().hex
        reservation_key = (
            f"usage:{{{user_id}}}:reservation:{reservation_id}"
        )

        redis_client.set(old_daily_key, 1000)
        redis_client.set(monthly_key, 1000)

        redis_client.hset(
            reservation_key,
            mapping={
                "reservation_id": reservation_id,
                "requested_tokens": 1000,
                "daily_key": old_daily_key,
                "monthly_key": monthly_key,
                "status": "reserved",
                "created_at": int(previous_day.timestamp()),
                "expires_at": int(
                    (previous_day + timedelta(minutes=10)).timestamp()
                )
            }
        )

        redis_client.zadd(
            f"usage:{{{user_id}}}:reservations:expiry",
            {
                reservation_id: int(
                    (previous_day + timedelta(minutes=10)).timestamp()
                )
            }
        )

        result = release_tokens(user_id, reservation_id)

        assert result["status"] == "released"
        assert result["daily_used"] == 0
        assert result["monthly_used"] == 0

        assert int(redis_client.get(old_daily_key)) == 0
        assert int(redis_client.get(monthly_key)) == 0

        # New day's counter must remain untouched.
        assert redis_client.get(new_daily_key) is None

    finally:
        cleanup_user(user_id)
        redis_client.delete(
            f"usage:{{{user_id}}}:daily:2026-11-08",
            f"usage:{{{user_id}}}:daily:2026-11-09",
            f"usage:{{{user_id}}}:monthly:2026-11"
        )

def test_daily_and_monthly_quota_ttl():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        before = datetime.now(timezone.utc)

        reserve_tokens(user_id, 1000)

        daily_key = (
            f"usage:{{{user_id}}}:daily:{before:%Y-%m-%d}"
        )
        monthly_key = (
            f"usage:{{{user_id}}}:monthly:{before:%Y-%m}"
        )

        daily_ttl = redis_client.ttl(daily_key)
        monthly_ttl = redis_client.ttl(monthly_key)

        after = datetime.now(timezone.utc)

        next_day = (before + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        next_month = (
            before.replace(day=28) + timedelta(days=4)
        ).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        expected_daily_ttl = int((next_day - after).total_seconds())
        expected_monthly_ttl = int((next_month - after).total_seconds())

        assert 0 < daily_ttl <= expected_daily_ttl + 2
        assert 0 < monthly_ttl <= expected_monthly_ttl + 2

    finally:
        cleanup_user(user_id)

def test_concurrent_reservations_respect_daily_quota(monkeypatch):
    user_id = f"test_{uuid.uuid4().hex}"

    monkeypatch.setitem(USAGE_LIMITS, "daily_tokens", 1000)
    monkeypatch.setitem(USAGE_LIMITS, "monthly_tokens", 5000)

    def make_reservation():
        try:
            return reserve_tokens(user_id, 700)
        except HTTPException as exc:
            return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: make_reservation(),
                    range(2)
                )
            )

        successful = [
            result for result in results
            if isinstance(result, dict)
        ]

        rejected = [
            result for result in results
            if result == 429
        ]

        assert len(successful) == 1
        assert len(rejected) == 1

        daily_key = (
            f"usage:{{{user_id}}}:daily:"
            f"{datetime.now(timezone.utc):%Y-%m-%d}"
        )

        assert int(redis_client.get(daily_key)) == 700

    finally:
        cleanup_user(user_id)

def test_concurrent_reservations_for_different_users(monkeypatch):
    user_a = f"test_{uuid.uuid4().hex}"
    user_b = f"test_{uuid.uuid4().hex}"

    monkeypatch.setitem(USAGE_LIMITS, "daily_tokens", 1000)
    monkeypatch.setitem(USAGE_LIMITS, "monthly_tokens", 5000)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda user_id: reserve_tokens(user_id, 700),
                    [user_a, user_b]
                )
            )

        assert len(results) == 2

        for user_id in (user_a, user_b):
            daily_key = (
                f"usage:{{{user_id}}}:daily:"
                f"{datetime.now(timezone.utc):%Y-%m-%d}"
            )

            assert int(redis_client.get(daily_key)) == 700

    finally:
        cleanup_user(user_a)
        cleanup_user(user_b)

def test_concurrent_reconciliation_only_succeeds_once():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        def reconcile():
            try:
                return reconcile_tokens(
                    user_id, reservation_id, 700
                )
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _: reconcile(), range(2))
            )

        successful = [
            result for result in results
            if isinstance(result, dict)
        ]

        rejected = [
            result for result in results
            if result == 409
        ]

        assert len(successful) == 1
        assert len(rejected) == 1

        daily_key = (
            f"usage:{{{user_id}}}:daily:"
            f"{datetime.now(timezone.utc):%Y-%m-%d}"
        )

        monthly_key = (
            f"usage:{{{user_id}}}:monthly:"
            f"{datetime.now(timezone.utc):%Y-%m}"
        )

        assert int(redis_client.get(daily_key)) == 700
        assert int(redis_client.get(monthly_key)) == 700

    finally:
        cleanup_user(user_id)

def test_concurrent_release_only_succeeds_once():
    user_id = f"test_{uuid.uuid4().hex}"

    try:
        reservation = reserve_tokens(user_id, 1000)
        reservation_id = reservation["reservation_id"]

        def release():
            try:
                return release_tokens(user_id, reservation_id)
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _: release(), range(2))
            )

        successful = [
            result for result in results
            if isinstance(result, dict)
        ]

        rejected = [
            result for result in results
            if result == 409
        ]

        assert len(successful) == 1
        assert len(rejected) == 1

        daily_key = (
            f"usage:{{{user_id}}}:daily:"
            f"{datetime.now(timezone.utc):%Y-%m-%d}"
        )

        monthly_key = (
            f"usage:{{{user_id}}}:monthly:"
            f"{datetime.now(timezone.utc):%Y-%m}"
        )

        assert int(redis_client.get(daily_key)) == 0
        assert int(redis_client.get(monthly_key)) == 0

    finally:
        cleanup_user(user_id)