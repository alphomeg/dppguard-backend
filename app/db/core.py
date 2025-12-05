from app.core.config import settings
from sqlmodel import create_engine
from sqlmodel import Session, create_engine


engine = create_engine(settings.database_url)


def get_session():
    with Session(engine) as session:
        yield session
