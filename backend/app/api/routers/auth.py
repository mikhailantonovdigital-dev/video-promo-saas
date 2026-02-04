from __future__ import annotations

from app.api.deps import get_db, get_current_user

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    random_token_urlsafe,
    sha256_hex,
    verify_password,
)
from app.db.session import AsyncSessionLocal
from app.models.email_verification import EmailVerification
from app.models.session_token import UserSession
from app.models.user import User
from app.schemas.auth import LoginIn, MeOut, SignupIn

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(req: Request) -> str | None:
    return req.client.host if req.client else None


@router.post("/signup", status_code=201)
async def signup(payload: SignupIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    if not all(
        [
            payload.consent_rights,
            payload.consent_face,
            payload.consent_no_third_party,
            payload.consent_storage,
            payload.consent_terms,
        ]
    ):
        raise HTTPException(status_code=400, detail="All consents are required")

    email = str(payload.email).lower()

    q = await db.execute(select(User).where(User.email == email))
    if q.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        consent_version="v1.0",
        consented_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    token = random_token_urlsafe()
    ev = EmailVerification(
        user_id=user.id,
        token_hash=sha256_hex(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(ev)
    await db.commit()

    verify_link = f"https://{settings.app_domain}/verify-email?token={token}"

    # Пока реальной почты нет — в dev возвращаем ссылку ответом.
    return {
        "ok": True,
        "message": "Check your email to verify",
        "dev_verify_link": verify_link if settings.env != "prod" else None,
    }


@router.post("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    token_hash = sha256_hex(token)
    q = await db.execute(
        select(EmailVerification).where(
            EmailVerification.token_hash == token_hash,
            EmailVerification.consumed_at.is_(None),
        )
    )
    ev = q.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=400, detail="Invalid or used token")
    if ev.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token expired")

    await db.execute(
        update(EmailVerification).where(EmailVerification.id == ev.id).values(consumed_at=datetime.now(timezone.utc))
    )
    await db.execute(
        update(User).where(User.id == ev.user_id, User.email_verified_at.is_(None)).values(
            email_verified_at=datetime.now(timezone.utc)
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/login")
async def login(payload: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    email = str(payload.email).lower()
    q = await db.execute(select(User).where(User.email == email))
    user = q.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.email_verified_at:
        raise HTTPException(status_code=403, detail="Email not verified")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access = create_access_token(sub=str(user.id))
    refresh = create_refresh_token(sub=str(user.id))

    sess = UserSession(
        user_id=user.id,
        refresh_token_hash=sha256_hex(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
    )
    db.add(sess)

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    secure_cookie = settings.env == "prod"  # в dev можно тестить без https
    response.set_cookie("access_token", access, httponly=True, secure=secure_cookie, samesite="lax", max_age=60 * settings.access_token_minutes)
    response.set_cookie("refresh_token", refresh, httponly=True, secure=secure_cookie, samesite="lax", max_age=60 * 60 * 24 * settings.refresh_token_days)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(email=user.email, role=user.role, email_verified=bool(user.email_verified_at))

from pydantic import EmailStr  # добавь импорт вверху, если нет

@router.post("/bootstrap-admin")
async def bootstrap_admin(
    email: EmailStr,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Защита: только если задан секрет в env и он совпал
    if not settings.admin_bootstrap_token or token != settings.admin_bootstrap_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    q = await db.execute(select(User).where(User.email == str(email).lower()))
    user = q.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.email_verified_at:
        raise HTTPException(status_code=400, detail="User email not verified")

    user.role = "admin"
    await db.commit()
    return {"ok": True, "email": user.email, "role": user.role}
