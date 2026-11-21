"""Password hashing, JWT creation/verification and FastAPI auth dependencies."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import RefreshToken, User

settings = get_settings()
ALGORITHM = "HS256"
REFRESH_COOKIE = "ks_refresh"

# ---------- passwords ----------

# Used when a phone number is not registered, so the response takes as long as a
# real check and attackers cannot discover which numbers have accounts.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=12))


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; pre-hashing keeps long passphrases safe.
    digest = hashlib.sha256(password.encode()).hexdigest().encode()
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    digest = hashlib.sha256(password.encode()).hexdigest().encode()
    if not hashed:
        bcrypt.checkpw(digest, _DUMMY_HASH)
        return False
    return bcrypt.checkpw(digest, hashed.encode())


# ---------- tokens ----------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_access_token(user: User) -> str:
    now = _now()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "ver": user.token_version,
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_refresh_token(db: Session, user: User, family: str | None = None) -> str:
    now = _now()
    jti = secrets.token_urlsafe(32)
    family = family or secrets.token_urlsafe(16)
    expires = now + timedelta(days=settings.refresh_token_days)
    db.add(RefreshToken(user_id=user.id, jti_hash=_sha256(jti), family=family, expires_at=expires))
    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "fam": family,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": expires,
        "jti": jti,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],  # never accept "none" or other algorithms
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return payload


def user_from_access_token(db: Session, token: str) -> User:
    payload = decode_token(token, "access")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or payload.get("ver") != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is no longer valid")
    return user


def rotate_refresh_token(db: Session, token: str) -> tuple[User, str]:
    """Validate a refresh token, mark it used and issue a new one in the same family."""
    payload = decode_token(token, "refresh")
    record = db.query(RefreshToken).filter_by(jti_hash=_sha256(payload["jti"])).first()
    if record is None or record.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    if record.used:
        # Replay of an already-rotated token: assume theft, kill the whole session family.
        db.query(RefreshToken).filter_by(family=record.family).update({"revoked": True})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    record.used = True
    new_token = create_refresh_token(db, user, family=record.family)
    db.commit()
    return user, new_token


def revoke_refresh_family(db: Session, token: str) -> None:
    try:
        payload = decode_token(token, "refresh")
    except HTTPException:
        return
    db.query(RefreshToken).filter_by(family=payload.get("fam")).update({"revoked": True})
    db.commit()


# ---------- dependencies ----------

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in", headers={"WWW-Authenticate": "Bearer"})
    return user_from_access_token(db, creds.credentials)


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not allowed to do this")
        return user

    return checker
