from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, HttpUrl


class URLCreate(BaseModel):
    original_url: HttpUrl
    expires_in_hours: Optional[int] = None


class URLResponse(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UrlItem(BaseModel):
    short_code: str
    original_url: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
