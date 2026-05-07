from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl


class URLCreate(BaseModel):
    original_url: HttpUrl
    expires_in_hours: Optional[int] = None


class URLResponse(BaseModel):
    short_code: str
    original_url: str
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
