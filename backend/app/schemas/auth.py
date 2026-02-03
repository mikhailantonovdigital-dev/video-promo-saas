from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    consent_rights: bool
    consent_face: bool
    consent_no_third_party: bool
    consent_storage: bool
    consent_terms: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MeOut(BaseModel):
    email: EmailStr
    role: str
    email_verified: bool
