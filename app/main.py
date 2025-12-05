import uvicorn
from fastapi import FastAPI

from app.api.v1 import index
from app.api.v1 import auth
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(title=settings.app_name)

# Register routes
app.include_router(index.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth")

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        log_level=None,
    )
