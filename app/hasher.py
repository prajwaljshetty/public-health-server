# Password Hasher :
from argon2 import PasswordHasher
from argon2.exceptions import(
    InvalidHashError,
    VerificationError , 
    VerifyMismatchError
)

password_hasher = PasswordHasher()

def hash_password(password: str) -> str:
    # Hashed password
    return password_hasher.hash(password = password)

def verify_password(password: str , hashed_password: str) -> bool:
    try :
        # Hash(Password , salt) == hashed_password
        return password_hasher.verify(hash = hashed_password , password = password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
