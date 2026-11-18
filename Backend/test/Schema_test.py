from Model.schema import CreateMessages

test_cases = [
    "Hello",
    "",
    "     ",
    "   Hello AI   ",
]

for content in test_cases:
    try:
        result = CreateMessages(content=content)
        print("Accepted:", repr(result.content))

    except Exception as e:
        print("Rejected:", e)