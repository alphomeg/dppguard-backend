import base64
import os
import shutil
import uuid
from pathlib import Path
from fastapi import UploadFile
from app.core.config import settings


# Define storage location (using Path for OS agnostic handling)
PRODUCT_IMG_DIR = Path(settings.static_dir) / "products"
STATIC_URL_PREFIX = "/static/products"

ARTIFACT_DIR = Path(settings.static_dir) / "artifacts"
ARTIFACT_URL_PREFIX = "/static/artifacts"


def save_base64_image(base64_str: str) -> str:
    """
    Decodes a Base64 image string, saves it to the static directory,
    and returns the public URL.
    """
    if not base64_str:
        return None

    # 1. Ensure directory exists
    os.makedirs(PRODUCT_IMG_DIR, exist_ok=True)

    # 2. Parse Base64 string
    # Frontend usually sends: "data:image/png;base64,iVBORw0KGgoAAA..."
    if "," in base64_str:
        header, encoded = base64_str.split(",", 1)
        if "image/jpeg" in header:
            ext = "jpg"
        elif "image/webp" in header:
            ext = "webp"
        else:
            ext = "png"
    else:
        encoded = base64_str
        ext = "png"

    # 3. Generate unique filename
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = PRODUCT_IMG_DIR / filename

    try:
        # 4. Decode and Write
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(encoded))

        # 5. Return Web-Accessible URL
        return f"{settings.public_url}{STATIC_URL_PREFIX}/{filename}"

    except Exception as e:
        # Log this error in production
        print(f"Error saving image: {e}")
        raise e


def save_upload_file(upload_file: UploadFile) -> str:
    """
    Saves a binary UploadFile stream to the local static/artifacts directory
    and returns the public URL.
    """
    # 1. Ensure directory exists
    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    # 2. Generate unique filename
    # Preserve extension if possible, else default to .bin
    original_filename = upload_file.filename or "unknown"
    ext = original_filename.split(
        ".")[-1] if "." in original_filename else "bin"

    unique_name = f"{uuid.uuid4()}.{ext}"
    file_path = ARTIFACT_DIR / unique_name

    try:
        # 3. Write binary stream
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)

        # 4. Return Web-Accessible URL
        # e.g. http://localhost:8000/static/artifacts/uuid.pdf
        return f"{settings.public_url}{ARTIFACT_URL_PREFIX}/{unique_name}"

    except Exception as e:
        print(f"Error saving artifact: {e}")
        raise e
