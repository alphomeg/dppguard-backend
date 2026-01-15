import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import index
from app.api.v1 import user
from app.api.v1 import material_definition
from app.api.v1 import certification_definition
from app.api.v1 import supplier
from app.api.v1 import product
from app.api.v1 import product_contribution


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
app.include_router(user.router, prefix="/api/v1/users")
app.include_router(
    material_definition.router, prefix="/api/v1/materials", tags=["Materials"])
app.include_router(certification_definition.router,
                   prefix="/api/v1/certifications", tags=["Certifications"])
app.include_router(supplier.router,
                   prefix="/api/v1/suppliers", tags=["Suppliers"])
app.include_router(
    product.router,
    prefix="/api/v1/products",
    tags=["Products"]
)
app.include_router(
    product_contribution.router,
    prefix="/api/v1/product-contributions",
    tags=["Product Contributions"]
)

# app.include_router(
#     collaboration.router,
#     prefix="/api/v1/collaboration",
#     tags=["Collaboration Workflow"]
# )


# Static files serving
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        log_level=None,
    )
