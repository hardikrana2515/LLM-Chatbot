from pymongo import MongoClient
from dotenv import load_dotenv
import os


load_dotenv()

#connection
uri = os.getenv("MONGODB_URI")
db_name = os.getenv("DATABASE_NAME")

if not uri or not db_name:
    raise ValueError("MongoDB environment variables are missing")

client = MongoClient(uri ,serverSelectionTimeoutMS=5000)

#Database
db = client[db_name]

#collections
conversations_db = db["conversations"]
messages_db = db["messages"]
user_db = db["user"]
sessions_db = db["sessions"]
llm_usage_db = db["llm_usage"]

#make email unique (like pkey)
user_db.create_index("email", unique=True)

sessions_db.create_index("expiresAt", expireAfterSeconds=0)

messages_db.create_index([("conversation_id", 1),("user_id", 1),("client_message_id", 1)],
                         unique=True,
                         partialFilterExpression={
                             "client_message_id" : {"$type" : "string"}
                         })

llm_usage_db.create_index(
    [
        ("user_id", 1),
        ("createdAt", -1)
    ]
)

llm_usage_db.create_index(
    [
        ("conversation_id", 1),
        ("createdAt", -1)
    ]
)

llm_usage_db.create_index(
    "request_id",
    unique=True,
    partialFilterExpression={
        "request_id": {"$type": "string"}
    }
)

