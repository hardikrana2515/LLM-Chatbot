from Database.redis_db import check_redis_connection


def test_redis_connection():
    result = check_redis_connection()

    assert result["status"] == "connected"
    assert result["time"] is not None