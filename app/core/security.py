from pwdlib import PasswordHash
from dotenv import load_dotenv
from datetime import datetime, timedelta
from app.core.env_utils import get_env_variable
import jwt
import os

load_dotenv()

ph = PasswordHash.recommended()

SECRET_KEY = get_env_variable("SECRET_KEY")

ALGORITHM = get_env_variable("ALGORITHM")

ACCESS_TOKEN_EXPIRE_MINUTES = int(get_env_variable("ACCESS_TOKEN_EXPIRE_MINUTES"))


def hash_password(plain_password: str) -> str:
    return ph.hash(plain_password)


def verify_password(plain_password: str, hashed: str) -> bool:
    return ph.verify(plain_password, hashed)


def create_token_access(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token_access(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
