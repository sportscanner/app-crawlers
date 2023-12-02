START_TIME, END_TIME = "17:30", "22:00"
LOGGING_LEVEL = "DEBUG"
MAPPINGS = "mappings.json"

schema = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "encoded_alias": {"type": "string"}},
        "required": ["name", "encoded_alias"],
    },
}
