import base64
import os
import shutil
import uuid
from pathlib import Path
from fastapi import UploadFile, HTTPException
from app.core.config import settings


# Define storage location (using Path for OS agnostic handling)
PRODUCT_IMG_DIR = Path(settings.static_dir) / "products"
STATIC_URL_PREFIX = "/static/products"

ARTIFACT_DIR = Path(settings.static_dir) / "artifacts"
ARTIFACT_URL_PREFIX = "/static/artifacts"

# Allowed file extensions for certificates and documents
ALLOWED_CERTIFICATE_EXTENSIONS = {
    # Document formats
    "pdf",  # PDF documents
    "doc", "docx",  # Microsoft Word
    "xls", "xlsx",  # Microsoft Excel
    "ppt", "pptx",  # Microsoft PowerPoint
    "txt",  # Plain text
    "rtf",  # Rich Text Format
    "odt", "ods", "odp",  # OpenDocument formats
    # Image formats
    "png", "jpg", "jpeg",  # Common image formats
    "gif", "bmp", "tiff", "tif",  # Additional image formats
    "webp",  # WebP images
}


def validate_certificate_file_extension(filename: str) -> None:
    """
    Validates that the file extension is allowed for certificate uploads.
    Raises HTTPException if the extension is not allowed.
    """
    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required for certificate uploads."
        )

    # Extract extension (case-insensitive)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if not ext:
        raise HTTPException(
            status_code=400,
            detail="File must have an extension. Allowed extensions: " +
            ", ".join(sorted(ALLOWED_CERTIFICATE_EXTENSIONS))
        )

    if ext not in ALLOWED_CERTIFICATE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '.{ext}' is not allowed for certificates. Allowed extensions: {', '.join(sorted(ALLOWED_CERTIFICATE_EXTENSIONS))}"
        )


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


def save_upload_file(upload_file: UploadFile, validate_extension: bool = False) -> str:
    """
    Saves a binary UploadFile stream to the local static/artifacts directory
    and returns the public URL.

    Args:
        upload_file: The file to upload
        validate_extension: If True, validates that the file extension is allowed for certificates
    """
    # 1. Validate extension if requested (for certificates)
    if validate_extension:
        validate_certificate_file_extension(upload_file.filename or "")

    # 2. Ensure directory exists
    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    # 3. Generate unique filename
    # Preserve extension if possible, else default to .bin
    original_filename = upload_file.filename or "unknown"
    ext = original_filename.split(
        ".")[-1] if "." in original_filename else "bin"

    unique_name = f"{uuid.uuid4()}.{ext}"
    file_path = ARTIFACT_DIR / unique_name

    try:
        # 4. Write binary stream
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)

        # 5. Return Web-Accessible URL
        # e.g. http://localhost:8000/static/artifacts/uuid.pdf
        return f"{settings.public_url}{ARTIFACT_URL_PREFIX}/{unique_name}"

    except Exception as e:
        print(f"Error saving artifact: {e}")
        raise e
