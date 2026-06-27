"""
Security helpers: password hashing and JWT bearer tokens.

  * hash_password / verify_password -> turn a plain password into a safe,
    one-way bcrypt hash, and check a login attempt against a stored hash.
  * create_access_token / decode_access_token -> issue and read the bearer
    token a client sends on every authenticated request.

A JWT (JSON Web Token) is a signed string. We put the user's id inside it and
sign it with settings.jwt_secret. The client stores the token after login and
sends it back as `Authorization: Bearer <token>`. Because it is signed, we can
trust its contents without a database lookup, as long as the secret stays secret.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext

from app.config.settings import settings

# bcrypt is the hashing algorithm. "deprecated=auto" lets us upgrade algorithms
# later without breaking old hashes.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Turn a plain-text password into a bcrypt hash for storage."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a login attempt against the stored hash. Returns True/False."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str | int, expires_minutes: Optional[int] = None) -> str:
    """
    Create a signed bearer token. `subject` is who the token is about — we use
    the user's id. `exp` is the expiry time the token becomes invalid.
    """
    minutes = expires_minutes or settings.access_token_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": str(subject), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[int]:
    """
    Verify a token's signature and expiry. Returns the user id inside it, or
    None if the token is invalid/expired/tampered.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        return int(subject) if subject is not None else None
    except (jwt.PyJWTError, ValueError):
        return None
