import logging
import random
import string
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import URL
from app.schemas import URLCreate, URLResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="URL Shortener")


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@app.post("/shorten", response_model=URLResponse, status_code=201)
def shorten_url(payload: URLCreate, db: Session = Depends(get_db)):
    expires_at = None
    if payload.expires_in_hours is not None:
        expires_at = datetime.utcnow() + timedelta(hours=payload.expires_in_hours)

    for _ in range(10):
        code = _generate_code()
        if not db.query(URL).filter(URL.short_code == code).first():
            break
    else:
        raise HTTPException(status_code=500, detail="Could not generate unique code")

    url_obj = URL(
        original_url=str(payload.original_url),
        short_code=code,
        expires_at=expires_at,
    )
    db.add(url_obj)
    db.commit()
    db.refresh(url_obj)
    logger.info({"event": "url_created", "code": code, "expires_at": str(expires_at)})
    return url_obj


@app.get("/{code}")
def redirect_url(code: str, db: Session = Depends(get_db)):
    url_obj = db.query(URL).filter(URL.short_code == code).first()
    if not url_obj:
        raise HTTPException(status_code=404, detail="URL not found")

    if url_obj.expires_at is not None and url_obj.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="URL has expired")

    logger.info({"event": "url_redirected", "code": code})
    return RedirectResponse(url=url_obj.original_url, status_code=302)
