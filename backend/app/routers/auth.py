from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..limiter import limiter
from ..models import RefreshToken, User, WorkerProfile
from ..schemas import ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut
from ..security import (
    REFRESH_COOKIE,
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    revoke_refresh_family,
    rotate_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _check_origin(request: Request) -> None:
    """CSRF defence for cookie-authenticated endpoints (on top of SameSite=Strict)."""
    origin = request.headers.get("origin")
    if origin and origin not in settings.origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,  # JavaScript cannot read it, so XSS cannot steal it
        secure=settings.is_production,  # HTTPS only in production
        samesite="strict",
        path="/api/auth",  # only sent to auth endpoints
    )


def _token_response(db: Session, response: Response, user: User) -> TokenOut:
    refresh = create_refresh_token(db, user)
    db.commit()
    _set_refresh_cookie(response, refresh)
    return TokenOut(
        access_token=create_access_token(user),
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, response: Response, body: RegisterIn, db: Session = Depends(get_db)):
    _check_origin(request)
    if db.query(User).filter_by(phone=body.phone).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This mobile number is already registered")
    user = User(
        name=body.name,
        phone=body.phone,
        password_hash=hash_password(body.password),
        role=body.role,
        city=body.city,
    )
    db.add(user)
    db.flush()
    if user.role == "worker":
        db.add(WorkerProfile(user_id=user.id, city=body.city))
    return _token_response(db, response, user)


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, response: Response, body: LoginIn, db: Session = Depends(get_db)):
    _check_origin(request)
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong mobile number or password")
    user = db.query(User).filter_by(phone=body.phone).first()
    now = datetime.now(timezone.utc)

    if user and user.locked_until:
        locked_until = user.locked_until.replace(tzinfo=user.locked_until.tzinfo or timezone.utc)
        if locked_until > now:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a few minutes.")

    if not verify_password(body.password, user.password_hash if user else None):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                user.failed_logins = 0
            db.commit()
        raise generic
    if not user.is_active:
        raise generic

    user.failed_logins = 0
    user.locked_until = None
    return _token_response(db, response, user)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("30/minute")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    _check_origin(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    try:
        user, new_refresh = rotate_refresh_token(db, token)
    except HTTPException:
        response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
        raise
    _set_refresh_cookie(response, new_refresh)
    return TokenOut(
        access_token=create_access_token(user),
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _check_origin(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        revoke_refresh_family(db, token)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.status_code = 204
    return response


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1  # invalidates every access token already issued
    db.query(RefreshToken).filter_by(user_id=user.id).update({"revoked": True})
    db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.status_code = 204
    return response


@router.post("/change-password", status_code=204)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    db.query(RefreshToken).filter_by(user_id=user.id).update({"revoked": True})
    db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
