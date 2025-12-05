from fastapi import APIRouter, Depends, HTTPException, status
from app.db.core import get_session
from sqlmodel import Session, text
from loguru import logger

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
def index():
    return {"status": "API is running"}


@router.get("/readiness", status_code=status.HTTP_200_OK)
def readiness_check(session: Session = Depends(get_session)):
    try:
        session.exec(text("SELECT 1"))
    except Exception as e:
        logger.exception("Database readiness check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not ready"
        )

    return {"status": "ready", "database": "online"}
