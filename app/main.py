import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import index
from app.api.v1 import auth
from app.api.v1.references import materials
from app.api.v1.references import suppliers
from app.api.v1.references import certification
from app.api.v1 import products


from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(title=settings.app_name)

# Middlewares
origins = []

if settings.allowed_hosts:
    origins = settings.allowed_hosts.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(index.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth")

# References routes
app.include_router(materials.router, prefix="/api/v1/materials")
app.include_router(suppliers.router, prefix="/api/v1/suppliers")
app.include_router(certification.router, prefix="/api/v1/certifications")

# Product routes
app.include_router(products.router, prefix="/api/v1/products")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        log_level=None,
    )
