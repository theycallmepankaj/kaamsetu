"""Request/response models. Every input has strict types and length limits."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .skills import SKILL_KEYS

PHONE_RE = re.compile(r"^[6-9]\d{9}$")  # Indian mobile number, 10 digits


def _clean_text(v: str) -> str:
    # Strip control characters; keep Indic scripts, emoji, punctuation.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v).strip()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- auth ----------


class RegisterIn(Strict):
    name: str = Field(min_length=2, max_length=80)
    phone: str
    password: str = Field(min_length=8, max_length=128)
    role: Literal["worker", "employer"]
    city: str = Field(default="", max_length=60)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v).removeprefix("+91")
        if not PHONE_RE.match(v):
            raise ValueError("Enter a valid 10-digit Indian mobile number")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain letters and numbers")
        return v

    @field_validator("name", "city")
    @classmethod
    def _text(cls, v: str) -> str:
        return _clean_text(v)


class LoginIn(Strict):
    phone: str = Field(max_length=16)
    password: str = Field(max_length=128)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return re.sub(r"[\s-]", "", v).removeprefix("+91")


class ChangePasswordIn(Strict):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain letters and numbers")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    role: str
    city: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------- worker profile ----------


class ProfileIn(Strict):
    skills: list[str] = Field(min_length=1, max_length=6)
    experience_years: int = Field(ge=0, le=60)
    daily_wage: int = Field(ge=0, le=100000)
    city: str = Field(min_length=2, max_length=60)
    lat: float | None = Field(default=None, ge=6, le=38)  # India's bounding box
    lng: float | None = Field(default=None, ge=68, le=98)
    bio: str = Field(default="", max_length=500)
    available: bool = True

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in SKILL_KEYS]
        if bad:
            raise ValueError(f"Unknown skills: {', '.join(bad)}")
        return list(dict.fromkeys(v))

    @field_validator("city", "bio")
    @classmethod
    def _text(cls, v: str) -> str:
        return _clean_text(v)


class ProfileOut(BaseModel):
    skills: list[str]
    experience_years: int
    daily_wage: int
    city: str
    lat: float | None
    lng: float | None
    bio: str
    available: bool
    rating: float | None = None
    rating_count: int = 0


class ProfileParseIn(Strict):
    text: str = Field(min_length=3, max_length=1000)


class ProfileSuggestion(BaseModel):
    skills: list[str] = []
    experience_years: int | None = None
    daily_wage: int | None = None
    city: str | None = None
    bio: str | None = None


# ---------- jobs ----------


class JobIn(Strict):
    title: str = Field(min_length=3, max_length=120)
    skill: str
    description: str = Field(default="", max_length=2000)
    city: str = Field(min_length=2, max_length=60)
    area: str = Field(default="", max_length=120)
    lat: float | None = Field(default=None, ge=6, le=38)
    lng: float | None = Field(default=None, ge=68, le=98)
    wage_per_day: int = Field(ge=100, le=100000)
    days: int = Field(ge=1, le=365)
    workers_needed: int = Field(ge=1, le=100)
    urgent: bool = False

    @field_validator("skill")
    @classmethod
    def _skill(cls, v: str) -> str:
        if v not in SKILL_KEYS:
            raise ValueError("Unknown skill")
        return v

    @field_validator("title", "description", "city", "area")
    @classmethod
    def _text(cls, v: str) -> str:
        return _clean_text(v)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employer_id: int
    employer_name: str = ""
    title: str
    skill: str
    description: str
    city: str
    area: str
    wage_per_day: int
    days: int
    workers_needed: int
    hired_count: int = 0
    applicant_count: int = 0
    urgent: bool = False
    status: str
    created_at: datetime
    distance_km: float | None = None
    my_application: "ApplicationOut | None" = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    worker_id: int
    worker_name: str = ""
    worker_phone: str | None = None  # only revealed to the employer after hiring
    worker_skills: list[str] = []
    worker_experience: int | None = None
    worker_rating: float | None = None
    status: str
    created_at: datetime


class StatusIn(Strict):
    status: Literal["on_the_way", "arrived", "completed", "withdrawn", "rejected"]


class RatingIn(Strict):
    stars: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=300)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    application_id: int
    sender_id: int
    text: str
    created_at: datetime


JobOut.model_rebuild()
