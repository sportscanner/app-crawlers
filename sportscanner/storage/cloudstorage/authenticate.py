import hashlib
from hashlib import pbkdf2_hmac

def derive_key_from_password(password, salt, iterations, hash_algorithm, bit_length, return_hex=True):
    # Convert password and salt to bytes
    password_bytes = password.encode('utf-8')
    salt_bytes = bytes.fromhex(salt)

    # Derive the key using PBKDF2
    derived_key = pbkdf2_hmac(hash_algorithm, password_bytes, salt_bytes, iterations, dklen=bit_length // 8)

    # Return the derived key as a hex string
    return derived_key.hex()

def generate_password_and_master_key(raw_password, salt):
    # Derive the key
    derived_key = derive_key_from_password(
        password=raw_password,
        salt=salt,
        iterations=200000,
        hash_algorithm="sha512",
        bit_length=512
    )

    # Split the derived key into two parts
    derived_master_keys = derived_key[:len(derived_key)//2]
    derived_password = derived_key[len(derived_key)//2:]

    # Hash the derived password using SHA-512
    derived_password_hash = hashlib.sha512(bytes.fromhex(derived_password)).hexdigest()

    return {
        'derivedMasterKeys': derived_master_keys,
        'derivedPassword': derived_password_hash
    }

# Example usage
raw_password = "java@Apple0"
salt = "36544F4D3433695945483066324C6D637273664167517A645867325A596261323744724373665A32553044656261653233336E773667756D7A62636E446C4A41306D346E4B6C5A674A4C6C7237645572586D5A706651556D364E6E437A4472777A6C4556334C6B46446F345665683743355730657378383461516C687232664C693179384E4F63703951676E4D6E317132596A6A61796C37677530627362366E67794D4D4E6B4B716348563064337073786A655567324963636C4664676E7355357645704F75676D73636A53477841367679644F315137594B7448396372335869326B3074795739536D7349666F62766370394337416630506E395538576977"  # Replace with your actual salt (hex encoded)

result = generate_password_and_master_key(raw_password, salt)
print(f"Derived Master Key: {result['derivedMasterKeys']}")
print(f"Derived Password (SHA-512): {result['derivedPassword']}")