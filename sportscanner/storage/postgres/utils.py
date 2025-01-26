import hashlib


def generate_composite_key(fields: list) -> str:
    combined = "|".join(
        str(field) for field in fields
    )  # Use a delimiter unlikely to appear in data
    full_hash = hashlib.md5(combined.encode()).hexdigest()  # MD5 hash
    return full_hash[:8]  # Truncate to desired length
