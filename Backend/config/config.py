RATE_LIMITS = {
    "signup": {
        "capacity": 10,
        "refill_rate": 10 / 60
    },
    "login_ip": {
        "capacity": 20,
        "refill_rate": 20 / 60
    },
    "login_account": {
        "capacity": 5,
        "refill_rate": 5 / 900
    },
    "refresh": {
        "capacity": 30,
        "refill_rate": 30 / 60
    },
    "create_message": {
        "capacity": 10,
        "refill_rate": 10 / 60
    },
    "fetch_conversations": {
        "capacity": 60,
        "refill_rate": 60 / 60
    },
    "fetch_messages" : {
        "capacity" : 60,
        "refill_rate" : 60/60
    }
}