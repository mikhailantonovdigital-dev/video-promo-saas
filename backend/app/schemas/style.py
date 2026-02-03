from __future__ import annotations

from pydantic import BaseModel, Field


class StyleOut(BaseModel):
    id: str
    code: str
    name: str
    description: str
    is_active: bool


class StyleCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    description: str = Field(default="", max_length=512)


class StyleUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    is_active: bool | None = None
