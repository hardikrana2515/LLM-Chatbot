
from Database.db import llm_usage_db


def get_usage_summary(user_id, period="daily"):

    if period == "daily":
        date_format = "%Y-%m-%d"

    elif period == "monthly":
        date_format = "%Y-%m"

    else:
        raise ValueError("Period must be daily or monthly")

    pipeline = [
        {
            "$match": {
                "user_id": user_id
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": date_format,
                        "date": "$createdAt",
                        "timezone": "UTC"
                    }
                },
                "total_requests": {"$sum": 1},
                "prompt_tokens": {"$sum": "$prompt_tokens"},
                "completion_tokens": {"$sum": "$completion_tokens"},
                "total_tokens": {"$sum": "$total_tokens"},
                "reasoning_tokens": {"$sum": "$reasoning_tokens"}
            }
        },
        {
            "$sort": {
                "_id": -1
            }
        }
    ]

    results = list(llm_usage_db.aggregate(pipeline))

    return [
        {
            "period": item["_id"],
            "total_requests": item["total_requests"],
            "prompt_tokens": item["prompt_tokens"],
            "completion_tokens": item["completion_tokens"],
            "total_tokens": item["total_tokens"],
            "reasoning_tokens": item["reasoning_tokens"]
        }
        for item in results
    ]
