from fastapi import HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from APIs.routes import messages as messages_api
from Database.db import messages_db, llm_usage_db
from Database.redis_db import redis_client
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pymongo.errors import ServerSelectionTimeoutError


def test_successful_message_creation(message_test_context, monkeypatch):

    # 1. Prepare a mocked LLM response.
    mock_llm_result = {
        "content": "An API allows two applications to communicate.",
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 25,
            "total_tokens": 145,
            "reasoning_tokens": 0
        },
        "model": "openai/gpt-oss-120b",
        "request_id": "test-request-unique-id",
        "finish_reason": "stop",
        "timing": {
            "prompt_time": 0.02,
            "completion_time": 0.05,
            "total_time": 0.07
        }
    }

    # 2. Mock only external/background operations.
    monkeypatch.setattr(
        messages_api,
        "generate_response",
        lambda chat_history: mock_llm_result
    )

    monkeypatch.setattr(
        messages_api,
        "update_conversation_summary",
        lambda conversation: None
    )

    # 3. Get authenticated test context.
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # 4. Send the actual HTTP request.
    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={
            "content": "Explain what an API is."
        },
        headers={
            "Idempotency-Key": "test-message-unique-001"
        }
    )

    # 5. Verify HTTP response.
    assert response.status_code == 200

    response_data = response.json()

    assert response_data["status_code"] == 201
    assert response_data["message"] == "message created successfully"

    # 6. Verify user message.
    user_message = response_data["data"]["user_message"]

    assert user_message["content"] == "Explain what an API is."
    assert user_message["role"] == "user"
    assert user_message["status"] == "completed"

    # 7. Verify assistant response.
    assistant_message = response_data["data"]["assistant_message"]

    assert assistant_message["content"] == mock_llm_result["content"]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["status"] == "completed"

    assert assistant_message["in_reply_to_message_id"] == user_message["id"]

    # 8. Verify MongoDB persistence.
    saved_user_message = messages_db.find_one({
        "_id": ObjectId(user_message["id"]),
        "user_id": user_id
    })

    saved_assistant_message = messages_db.find_one({
        "_id": ObjectId(assistant_message["id"]),
        "user_id": user_id
    })

    assert saved_user_message is not None
    assert saved_assistant_message is not None

    assert saved_assistant_message["status"] == "completed"

    # 9. Verify actual LLM usage was recorded.
    usage_record = llm_usage_db.find_one({
        "request_id": mock_llm_result["request_id"],
        "user_id": user_id
    })

    assert usage_record is not None
    assert usage_record["prompt_tokens"] == 120
    assert usage_record["completion_tokens"] == 25
    assert usage_record["total_tokens"] == 145

    # 10. Verify Redis quota reconciliation.
# 10. Verify Redis quota reconciliation.
    now = datetime.now(timezone.utc)

    daily_key = f"usage:{{{user_id}}}:daily:{now.strftime('%Y-%m-%d')}"
    monthly_key = f"usage:{{{user_id}}}:monthly:{now.strftime('%Y-%m')}"

    assert int(redis_client.get(daily_key)) == 145
    assert int(redis_client.get(monthly_key)) == 145


def test_message_idempotency(message_test_context, monkeypatch):

    # Track how many times the LLM is called.
    llm_call_count = 0

    mock_llm_result = {
        "content": "An API allows applications to communicate.",
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 25,
            "total_tokens": 145,
            "reasoning_tokens": 0
        },
        "model": "openai/gpt-oss-120b",
        "request_id": "idempotency-test-request",
        "finish_reason": "stop",
        "timing": {
            "prompt_time": 0.02,
            "completion_time": 0.05,
            "total_time": 0.07
        }
    }

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return mock_llm_result

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    monkeypatch.setattr(
        messages_api,
        "update_conversation_summary",
        lambda conversation: None
    )

    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    request_data = {
        "content": "Explain what an API is."
    }

    request_headers = {
        "Idempotency-Key": "same-request-idempotency-001"
    }

    # First request.
    first_response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json=request_data,
        headers=request_headers
    )

    assert first_response.status_code == 200

    first_data = first_response.json()["data"]

    # Second request with exactly the same idempotency key.
    second_response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json=request_data,
        headers=request_headers
    )

    assert second_response.status_code == 200

    second_data = second_response.json()["data"]

    # Both requests must return the same messages.
    assert (
        first_data["user_message"]["id"]
        == second_data["user_message"]["id"]
    )

    assert (
        first_data["assistant_message"]["id"]
        == second_data["assistant_message"]["id"]
    )

    # LLM must execute only once.
    assert llm_call_count == 1

    # Only one user and one assistant message should exist.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"]
    }) == 2

    # Usage must be recorded only once.
    assert llm_usage_db.count_documents({
        "user_id": user_id,
        "request_id": mock_llm_result["request_id"]
    }) == 1

    # Quota must not be charged twice.
    now = datetime.now(timezone.utc)

    daily_key = (
        f"usage:{{{user_id}}}:daily:{now.strftime('%Y-%m-%d')}"
    )

    monthly_key = (
        f"usage:{{{user_id}}}:monthly:{now.strftime('%Y-%m')}"
    )

    assert int(redis_client.get(daily_key)) == 145
    assert int(redis_client.get(monthly_key)) == 145


def test_cannot_send_message_to_another_users_conversation(
    message_test_context
):
    from datetime import datetime, timezone
    from bson import ObjectId
    from Database.db import conversations_db, messages_db

    client = message_test_context["client"]
    user = message_test_context["user"]

    # Create a conversation owned by a different user.
    other_user_id = ObjectId()
    other_conversation_id = ObjectId()
    now = datetime.now(timezone.utc)

    conversations_db.insert_one({
        "_id": other_conversation_id,
        "user_id": other_user_id,
        "title": "Another User's Conversation",
        "summary": "",
        "summary_through_message_id": None,
        "summary_updated_at": None,
        "createdAt": now,
        "updatedAt": now
    })

    # Attempt to access it using the authenticated test user's token.
    response = client.post(
        f"/api/messages/create/{other_conversation_id}/message",
        json={"content": "Try accessing another user's conversation."},
        headers={
            "Idempotency-Key": "ownership-test-001"
        }
    )

    assert response.status_code == 404

    # No message should have been created.
    assert messages_db.count_documents({
        "user_id": user["_id"],
        "conversation_id": other_conversation_id
    }) == 0

    # Clean up the foreign conversation.
    conversations_db.delete_one({
        "_id": other_conversation_id
    })


def test_llm_failure_releases_token_reservation(
    message_test_context,
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from Database.db import messages_db
    from Database.redis_db import redis_client
    from bson import ObjectId

    def mock_generate_response(chat_history):
        raise ValueError("Simulated LLM failure")

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    monkeypatch.setattr(
        messages_api,
        "update_conversation_summary",
        lambda conversation: None
    )

    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test LLM failure handling."},
        headers={
            "Idempotency-Key": "llm-failure-test-001"
        }
    )

    assert response.status_code == 502

    # Verify the assistant message was marked as failed.
    assistant_message = messages_db.find_one({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "assistant"
    })

    assert assistant_message is not None
    assert assistant_message["status"] == "failed"

    # Verify the reservation was released.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert len(reservation_keys) == 1

    reservation = redis_client.hgetall(reservation_keys[0])

    assert reservation["status"] == "released"

    # Verify reserved usage was returned.
    now = datetime.now(timezone.utc)

    daily_key = (
        f"usage:{{{user_id}}}:daily:{now.strftime('%Y-%m-%d')}"
    )

    monthly_key = (
        f"usage:{{{user_id}}}:monthly:{now.strftime('%Y-%m')}"
    )

    assert int(redis_client.get(daily_key)) == 0
    assert int(redis_client.get(monthly_key)) == 0


def test_daily_quota_rejection(message_test_context, monkeypatch):

    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # Fill the user's daily quota.
    now = datetime.now(timezone.utc)

    daily_key = (
        f"usage:{{{user_id}}}:daily:{now.strftime('%Y-%m-%d')}"
    )

    redis_client.set(
        daily_key,
        50000,
        ex=86400
    )

    # Track whether the LLM is called.
    llm_call_count = 0

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test daily quota rejection."},
        headers={
            "Idempotency-Key": "daily-quota-test-001"
        }
    )

    # The request must be rejected.
    assert response.status_code == 429

    # LLM must not be called.
    assert llm_call_count == 0

    # No reservation should have been created.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert reservation_keys == []

    # No messages should remain after rejection.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"]
    }) == 0


def test_concurrent_message_requests_with_same_idempotency_key(
    message_test_context,
    monkeypatch
):
    # Synchronize both requests after token reservation.
    reservation_barrier = Barrier(2)

    original_reserve_tokens = messages_api.reserve_tokens

    def synchronized_reserve_tokens(*args, **kwargs):
        reservation = original_reserve_tokens(*args, **kwargs)

        reservation_barrier.wait(timeout=10)

        return reservation

    monkeypatch.setattr(
        messages_api,
        "reserve_tokens",
        synchronized_reserve_tokens
    )

    # Track LLM generation calls.
    llm_calls = []

    mock_llm_result = {
        "content": "An API allows applications to communicate.",
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 25,
            "total_tokens": 145,
            "reasoning_tokens": 0
        },
        "model": "openai/gpt-oss-120b",
        "request_id": "concurrent-test-request",
        "finish_reason": "stop",
        "timing": {
            "prompt_time": 0.02,
            "completion_time": 0.05,
            "total_time": 0.07
        }
    }

    def mock_generate_response(chat_history):
        llm_calls.append(chat_history)
        return mock_llm_result

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    monkeypatch.setattr(
        messages_api,
        "update_conversation_summary",
        lambda conversation: None
    )

    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    request_data = {
        "content": "Explain what an API is."
    }

    request_headers = {
        "Idempotency-Key": "concurrent-request-001"
    }

    def send_request():
        return client.post(
            f"/api/messages/create/{conversation_id}/message",
            json=request_data,
            headers=request_headers
        )

    # Execute both requests concurrently.
    with ThreadPoolExecutor(max_workers=2) as executor:

        future_one = executor.submit(send_request)
        future_two = executor.submit(send_request)

        response_one = future_one.result(timeout=20)
        response_two = future_two.result(timeout=20)

    responses = [response_one, response_two]

    # Exactly one request should succeed.
    assert sorted(r.status_code for r in responses) == [200, 409]

    # LLM must execute exactly once.
    assert len(llm_calls) == 1

    # Only one user message should exist.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "user",
        "client_message_id": "concurrent-request-001"
    }) == 1

    # Only one assistant message should exist.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "assistant"
    }) == 1

    # Usage must be recorded only once.
    assert llm_usage_db.count_documents({
        "user_id": user_id,
        "request_id": mock_llm_result["request_id"]
    }) == 1

    # Quota must be charged only once.
    now = datetime.now(timezone.utc)

    daily_key = (
        f"usage:{{{user_id}}}:daily:{now.strftime('%Y-%m-%d')}"
    )

    monthly_key = (
        f"usage:{{{user_id}}}:monthly:{now.strftime('%Y-%m')}"
    )

    assert int(redis_client.get(daily_key)) == 145
    assert int(redis_client.get(monthly_key)) == 145

def test_mongodb_unavailable_during_conversation_lookup(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    conversation = message_test_context["conversation"]

    def mock_find_one(*args, **kwargs):
        raise ServerSelectionTimeoutError(
            "MongoDB server is unavailable"
        )

    monkeypatch.setattr(
        messages_api.conversations_db,
        "find_one",
        mock_find_one
    )

    response = client.post(
        f"/api/messages/create/{conversation['_id']}/message",
        json={"content": "Test MongoDB failure."},
        headers={
            "Idempotency-Key": "mongodb-failure-test-001"
        }
    )

    assert response.status_code == 503

    assert response.json()["detail"] == (
        "Database service is temporarily unavailable. Please try again."
    )


def test_mongodb_failure_during_user_message_insertion(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # Simulate MongoDB failure during user-message insertion.
    def mock_insert_one(*args, **kwargs):
        raise ServerSelectionTimeoutError(
            "MongoDB server is unavailable"
        )

    monkeypatch.setattr(
        messages_api.messages_db,
        "insert_one",
        mock_insert_one
    )

    # Track whether LLM generation is called.
    llm_call_count = 0

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test MongoDB insertion failure."},
        headers={
            "Idempotency-Key": "mongodb-insert-failure-001"
        }
    )

    # The API should return a controlled server error.
    assert response.status_code == 503

    # LLM must never be called.
    assert llm_call_count == 0

    # No user message should be created.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "user"
    }) == 0

    # Token reservation must be released.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert len(reservation_keys) == 1

    reservation = redis_client.hgetall(reservation_keys[0])

    assert reservation["status"] == "released"


def test_mongodb_failure_during_assistant_message_insertion(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # Preserve the real MongoDB insert operation.
    original_insert_one = messages_api.messages_db.insert_one

    # Allow user-message insertion, but fail assistant-message insertion.
    def mock_insert_one(document, *args, **kwargs):
        if document.get("role") == "assistant":
            raise ServerSelectionTimeoutError(
                "MongoDB server is unavailable"
            )

        return original_insert_one(document, *args, **kwargs)

    monkeypatch.setattr(
        messages_api.messages_db,
        "insert_one",
        mock_insert_one
    )

    # Track LLM generation.
    llm_call_count = 0

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test assistant insertion failure."},
        headers={
            "Idempotency-Key": "mongodb-assistant-failure-001"
        }
    )

    # Database connection failure should return HTTP 503.
    assert response.status_code == 503

    # LLM must not be called.
    assert llm_call_count == 0

    # The user message should remain saved.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "user",
        "client_message_id": "mongodb-assistant-failure-001"
    }) == 1

    # No assistant message should exist.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "assistant"
    }) == 0

    # Token reservation must be released.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert len(reservation_keys) == 1

    reservation = redis_client.hgetall(reservation_keys[0])

    assert reservation["status"] == "released"


def test_retry_after_assistant_message_insertion_failure(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    original_insert_one = messages_api.messages_db.insert_one

    assistant_insert_failed = False
    llm_call_count = 0

    def mock_insert_one(document, *args, **kwargs):
        nonlocal assistant_insert_failed

        if document.get("role") == "assistant" and not assistant_insert_failed:
            assistant_insert_failed = True
            raise ServerSelectionTimeoutError(
                "MongoDB server is unavailable"
            )

        return original_insert_one(document, *args, **kwargs)

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api.messages_db,
        "insert_one",
        mock_insert_one
    )

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    headers = {
        "Idempotency-Key": "mongodb-retry-test-001"
    }

    url = f"/api/messages/create/{conversation_id}/message"

    # First request: assistant insertion fails.
    first_response = client.post(
        url,
        json={"content": "Test retry after partial failure."},
        headers=headers
    )

    assert first_response.status_code == 503

    # Retry using exactly the same idempotency key.
    second_response = client.post(
        url,
        json={"content": "Test retry after partial failure."},
        headers=headers
    )

    # Current behavior should reject the retry with HTTP 409.
    assert second_response.status_code == 409

    # No LLM generation should have occurred.
    assert llm_call_count == 0

    # Only one user message should exist.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "user",
        "client_message_id": "mongodb-retry-test-001"
    }) == 1

    # No assistant message should exist.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "role": "assistant"
    }) == 0

def test_mongodb_failure_during_idempotency_lookup(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # Simulate MongoDB failure during the idempotency lookup.
    original_find_one = messages_api.messages_db.find_one

    def mock_find_one(query, *args, **kwargs):
        if query.get("client_message_id") == "mongodb-idempotency-failure-001":
            raise ServerSelectionTimeoutError(
                "MongoDB server is unavailable"
            )

        return original_find_one(query, *args, **kwargs)

    monkeypatch.setattr(
        messages_api.messages_db,
        "find_one",
        mock_find_one
    )

    # Track whether LLM generation is called.
    llm_call_count = 0

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test idempotency lookup failure."},
        headers={
            "Idempotency-Key": "mongodb-idempotency-failure-001"
        }
    )

    # Database failure should return a controlled 503.
    assert response.status_code == 503

    assert response.json()["detail"] == (
        "Database service is temporarily unavailable. Please try again."
    )

    # LLM must not be called.
    assert llm_call_count == 0

    # No message should be created.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"]
    }) == 0

    # No token reservation should be created.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert reservation_keys == []

def test_mongodb_failure_during_message_history_retrieval(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # Simulate MongoDB failure during history retrieval.
    original_find = messages_api.messages_db.find

    def mock_find(query, *args, **kwargs):
        raise ServerSelectionTimeoutError(
            "MongoDB server is unavailable"
        )

    monkeypatch.setattr(
        messages_api.messages_db,
        "find",
        mock_find
    )

    # Track LLM calls.
    llm_call_count = 0

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test history retrieval failure."},
        headers={
            "Idempotency-Key": "mongodb-history-failure-001"
        }
    )

    # API should return a controlled 503.
    assert response.status_code == 503

    assert response.json()["detail"] == (
        "Database service is temporarily unavailable. Please try again."
    )

    # LLM must not be called.
    assert llm_call_count == 0

    # No messages should be created.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"]
    }) == 0

    # No token reservation should exist.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert reservation_keys == []

def test_redis_failure_during_token_reservation(
    message_test_context,
    monkeypatch
):
    client = message_test_context["client"]
    user = message_test_context["user"]
    conversation = message_test_context["conversation"]

    user_id = user["_id"]
    conversation_id = str(conversation["_id"])

    # Simulate Redis failure during token reservation.
    def mock_reserve_tokens(*args, **kwargs):
        raise HTTPException(
            status_code=503,
            detail="Usage quota service is temporarily unavailable."
        )

    monkeypatch.setattr(
        messages_api,
        "reserve_tokens",
        mock_reserve_tokens
    )

    # Track LLM generation.
    llm_call_count = 0

    def mock_generate_response(chat_history):
        nonlocal llm_call_count
        llm_call_count += 1
        return {}

    monkeypatch.setattr(
        messages_api,
        "generate_response",
        mock_generate_response
    )

    response = client.post(
        f"/api/messages/create/{conversation_id}/message",
        json={"content": "Test Redis reservation failure."},
        headers={
            "Idempotency-Key": "redis-reservation-failure-001"
        }
    )

    assert response.status_code == 503

    assert response.json()["detail"] == (
        "Usage quota service is temporarily unavailable."
    )

    # LLM must not be called.
    assert llm_call_count == 0

    # No user or assistant messages should be created.
    assert messages_db.count_documents({
        "user_id": user_id,
        "conversation_id": conversation["_id"]
    }) == 0

    # No reservation should have been created.
    reservation_keys = list(
        redis_client.scan_iter(
            match=f"usage:{{{user_id}}}:reservation:*"
        )
    )

    assert reservation_keys == []


def test_redis_connection_failure_during_token_reservation(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    # Skip expired-reservation cleanup for this test.
    # We want to isolate the reservation script failure.
    monkeypatch.setattr(
        usage_quota,
        "cleanup_expired_reservations",
        lambda user_id: 0
    )

    # Simulate Redis being unavailable.
    def mock_redis_eval(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        mock_redis_eval
    )

    # Call the actual service function.
    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reserve_tokens(
            user_id="redis-failure-test-user",
            requested_tokens=100
        )

    # Verify the service returns the expected error.
    assert exc_info.value.status_code == 503

    assert (
        exc_info.value.detail
        == "Usage quota service is temporarily unavailable."
    )

def test_redis_connection_failure_during_expired_reservation_cleanup(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    def mock_zrangebyscore(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrangebyscore",
        mock_zrangebyscore
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.cleanup_expired_reservations(
            "redis-cleanup-failure-user"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to recover expired token reservations."
    )


def test_redis_connection_failure_during_reservation_metadata_lookup(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrangebyscore",
        lambda *args, **kwargs: [b"reservation-123"]
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RedisConnectionError("Redis server unavailable")
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.cleanup_expired_reservations(
            "redis-metadata-failure-user"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to recover expired token reservations."
    )

def test_redis_connection_failure_during_cleanup_lua_execution(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrangebyscore",
        lambda *args, **kwargs: [b"reservation-123"]
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test"
        }
    )

    def mock_eval(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        mock_eval
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.cleanup_expired_reservations(
            "redis-cleanup-lua-failure-user"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to recover expired token reservations."
    )

def test_cleanup_removes_expired_reservation_with_missing_metadata(monkeypatch):
    from services import usage_quota

    removed_reservations = []

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrangebyscore",
        lambda *args, **kwargs: [b"missing-reservation"]
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {}
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrem",
        lambda key, reservation_id: removed_reservations.append(
            (key, reservation_id)
        )
    )

    result = usage_quota.cleanup_expired_reservations(
        "missing-metadata-user"
    )

    assert result == 0
    assert removed_reservations == [
        (
            "usage:{missing-metadata-user}:reservations:expiry",
            b"missing-reservation"
        )
    ]

def test_redis_failure_during_stale_reservation_removal(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrangebyscore",
        lambda *args, **kwargs: [b"missing-reservation"]
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {}
    )

    def mock_zrem(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "zrem",
        mock_zrem
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.cleanup_expired_reservations(
            "stale-reservation-removal-user"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to recover expired token reservations."
    )

def test_redis_connection_failure_during_token_release_metadata_lookup(
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    def mock_hgetall(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        mock_hgetall
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.release_tokens(
            "release-failure-user",
            "reservation-123"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to release token reservation."
    )

def test_redis_connection_failure_during_token_release_lua_execution(
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test"
        }
    )

    def mock_eval(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        mock_eval
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.release_tokens(
            "release-lua-failure-user",
            "reservation-123"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to release token reservation."
    )

def test_release_tokens_when_reservation_does_not_exist(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {}
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.release_tokens(
            "missing-reservation-user",
            "nonexistent-reservation"
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Token reservation not found."

def test_release_tokens_when_reservation_already_finalized(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [2, 0, 0, 0]
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.release_tokens(
            "finalized-reservation-user",
            "reservation-123"
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Token reservation is already finalized."
    )

def test_release_tokens_when_counter_keys_do_not_match(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [-2, 0, 0, 0]
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.release_tokens(
            "counter-mismatch-user",
            "reservation-123"
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Reservation counter keys do not match."
    )

def test_release_tokens_when_reservation_disappears_before_lua_execution(
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [-1, 0, 0, 0]
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.release_tokens(
            "disappeared-reservation-user",
            "reservation-123"
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Token reservation not found."

def test_release_tokens_successful_response(monkeypatch):
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [1, 150, 1200, 350]
    )

    result = usage_quota.release_tokens(
        "successful-release-user",
        "reservation-123"
    )

    assert result == {
        "status": "released",
        "released_tokens": 350,
        "daily_used": 150,
        "monthly_used": 1200
    }

def test_redis_connection_failure_during_reconciliation_metadata_lookup(
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    def mock_hgetall(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        mock_hgetall
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reconcile_tokens(
            "reconciliation-failure-user",
            "reservation-123",
            500
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to reconcile token usage."
    )

def test_redis_connection_failure_during_reconciliation_lua_execution(
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from redis.exceptions import ConnectionError as RedisConnectionError
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test",
            "requested_tokens": "1000"
        }
    )

    def mock_eval(*args, **kwargs):
        raise RedisConnectionError("Redis server unavailable")

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        mock_eval
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reconcile_tokens(
            "reconciliation-lua-failure-user",
            "reservation-123",
            500
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Unable to reconcile token usage."
    )

def test_reconcile_tokens_when_reservation_does_not_exist(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {}
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reconcile_tokens(
            "missing-reconciliation-user",
            "nonexistent-reservation",
            500
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Token reservation not found."

def test_reconcile_tokens_when_reservation_disappears_before_lua_execution(
    monkeypatch
):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test",
            "requested_tokens": "1000"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [-1, 0, 0, 0, 0, 0]
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reconcile_tokens(
            "disappeared-reconciliation-user",
            "reservation-123",
            500
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Token reservation not found."

def test_reconcile_tokens_successful_response(monkeypatch):
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test",
            "requested_tokens": "1000"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [1, 500, 1500, -500, 0, 0]
    )

    result = usage_quota.reconcile_tokens(
        "successful-reconciliation-user",
        "reservation-123",
        500
    )

    assert result == {
        "status": "reconciled",
        "reserved_tokens": 1000,
        "actual_tokens": 500,
        "adjustment": -500,
        "daily_used": 500,
        "monthly_used": 1500,
        "daily_over_limit": False,
        "monthly_over_limit": False
    }

def test_reconcile_tokens_when_reservation_already_finalized(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test",
            "requested_tokens": "1000"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [2, 0, 0, 0, 0, 0]
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reconcile_tokens(
            "finalized-reconciliation-user",
            "reservation-123",
            500
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Token reservation has already been reconciled."
    )

def test_reconcile_tokens_when_counter_keys_do_not_match(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services import usage_quota

    monkeypatch.setattr(
        usage_quota.redis_client,
        "hgetall",
        lambda *args, **kwargs: {
            "daily_key": "usage:daily:test",
            "monthly_key": "usage:monthly:test",
            "requested_tokens": "1000"
        }
    )

    monkeypatch.setattr(
        usage_quota.redis_client,
        "eval",
        lambda *args, **kwargs: [-2, 0, 0, 0, 0, 0]
    )

    with pytest.raises(HTTPException) as exc_info:
        usage_quota.reconcile_tokens(
            "counter-mismatch-reconciliation-user",
            "reservation-123",
            500
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Reservation counter keys do not match."
    )