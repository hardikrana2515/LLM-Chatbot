
import os
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from fastapi.testclient import TestClient

# Configure isolated test services BEFORE importing application modules.
os.environ["DATABASE_NAME"] = "chatbot_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"

from main import app
from Database.db import (
    db,
    user_db,
    sessions_db,
    conversations_db,
    messages_db,
    llm_usage_db
)
from Database.redis_db import redis_client
from services.auth import create_access_token


@pytest.fixture
def message_test_context():

    # Safety checks: never run these fixtures against production databases.
    if db.name != "chatbot_test":
        raise RuntimeError("Tests must use chatbot_test database")

    if redis_client.connection_pool.connection_kwargs.get("db") != 1:
        raise RuntimeError("Tests must use Redis database 1")

    now = datetime.now(timezone.utc)

    # 1. Create test user.
    user_id = ObjectId()

    user = {
        "_id": user_id,
        "first_name": "Test",
        "last_name": "User",
        "email": f"test-{uuid4().hex}@example.com",
        "createdAt": now,
        "updatedAt": now
    }

    user_db.insert_one(user)

    # 2. Create valid authenticated session.
    session_id = ObjectId()

    session = {
        "_id": session_id,
        "user_id": user_id,
        "revoked": False,
        "expiresAt": now + timedelta(days=1)
    }

    sessions_db.insert_one(session)

    # 3. Generate a real JWT access token.
    access_token = create_access_token(
        user_id=str(user_id),
        session_id=str(session_id)
    )

    # 4. Create test conversation.
    conversation_id = ObjectId()

    conversation = {
        "_id": conversation_id,
        "user_id": user_id,
        "title": "Integration Test Conversation",
        "summary": "",
        "summary_through_message_id": None,
        "summary_updated_at": None,
        "createdAt": now,
        "updatedAt": now
    }

    conversations_db.insert_one(conversation)

    # 5. Create authenticated API client.
    with TestClient(app) as client:

        client.headers.update({
            "Authorization": f"Bearer {access_token}"
        })

        yield {
            "client": client,
            "user": user,
            "conversation": conversation,
            "access_token": access_token
        }

    # 6. Clean up MongoDB test documents.
    messages_db.delete_many({"user_id": user_id})
    llm_usage_db.delete_many({"user_id": user_id})
    conversations_db.delete_many({"user_id": user_id})
    sessions_db.delete_many({"user_id": user_id})
    user_db.delete_one({"_id": user_id})

    # 7. Clean up Redis keys belonging to this test user.
    keys = list(redis_client.scan_iter(match=f"*{user_id}*"))

    if keys:
        redis_client.delete(*keys)