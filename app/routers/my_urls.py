from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.auth import get_required_current_user
from app.database import get_db
from app.models import URL
from app.schemas import UrlItem

router = APIRouter(prefix="/my", tags=["my-urls"])


@router.get("/urls", response_model=List[UrlItem])
def list_my_urls(
    user_id: int = Depends(get_required_current_user),
    db: Session = Depends(get_db),
):
    return db.query(URL).filter(URL.user_id == user_id).all()


@router.delete("/urls/{code}", status_code=204)
def delete_my_url(
    code: str,
    user_id: int = Depends(get_required_current_user),
    db: Session = Depends(get_db),
):
    url = db.query(URL).filter(URL.short_code == code).first()
    if not url:
        raise HTTPException(status_code=404, detail="URL not found")
    if url.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this URL")
    db.delete(url)
    db.commit()
