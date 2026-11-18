from services.usage_analytics import get_usage_summary
from Database.db import user_db

user = list(user_db.find({}))

if user:
    for one in user :
        print(one["first_name"]+" "+one["last_name"])
        print("DAILY USAGE:")
        if get_usage_summary(one["_id"], "daily") :
            print(get_usage_summary(one["_id"], "daily"))
        else :
            print("Not any data")

        print("MONTHLY USAGE:")
        if get_usage_summary(one["_id"], "daily") :
            print(get_usage_summary(one["_id"], "monthly"))
        else :
            print("Not any data")

        print(" ")