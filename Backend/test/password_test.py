from Model.schema import Create_user

passwords = [
    "hardik123",
    "Hardik123",
    "Hardik@123",
    "ABC@1234"
]

for password in passwords:
    try:
        user = Create_user(
            first_name="Hardik",
            last_name="Rana",
            email="test@example.com",
            password=password
        )
        print(password, "Accepted")

    except Exception as e:
        print(password, "Rejected:", e)