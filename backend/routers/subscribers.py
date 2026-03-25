from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import NewsletterSubscriber

router = APIRouter()


class SubscriberRequest(BaseModel):
    email: str


@router.post("/subscribers")
def subscribe(req: SubscriberRequest, db: Session = Depends(get_db)):
    """Subscribe an email to the daily newsletter."""
    existing = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == req.email
    ).first()
    if existing:
        if existing.unsubscribed_at:
            existing.unsubscribed_at = None
            db.commit()
            return {"status": "resubscribed"}
        return {"status": "already_subscribed"}
    db.add(NewsletterSubscriber(email=req.email))
    db.commit()
    return {"status": "subscribed"}


@router.delete("/subscribers")
def unsubscribe(req: SubscriberRequest, db: Session = Depends(get_db)):
    """Unsubscribe an email from the daily newsletter."""
    import datetime
    sub = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.email == req.email
    ).first()
    if sub:
        sub.unsubscribed_at = datetime.datetime.utcnow()
        db.commit()
    return {"status": "unsubscribed"}
