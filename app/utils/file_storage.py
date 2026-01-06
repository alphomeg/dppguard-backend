import base64
import os
import uuid
from app.core.config import settings


# Define storage location
PRODUCT_IMG_DIR = settings.static_dir / "products"
STATIC_URL_PREFIX = "/static/products"


def save_base64_image(base64_str: str) -> str:
    """
    Decodes a Base64 image string, saves it to the static directory,
    and returns the public URL.
    """
    # 1. Ensure directory exists
    os.makedirs(PRODUCT_IMG_DIR, exist_ok=True)

    # 2. Parse Base64 string
    # Frontend usually sends: "data:image/png;base64,iVBORw0KGgoAAA..."
    if "," in base64_str:
        header, encoded = base64_str.split(",", 1)

        # Simple extension detection
        if "image/jpeg" in header:
            ext = "jpg"
        elif "image/webp" in header:
            ext = "webp"
        else:
            ext = "png"  # default fallback
    else:
        # If raw string without header
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
        # e.g., http://localhost:8000/static/products/uuid.png
        return f"{settings.public_url}{STATIC_URL_PREFIX}/{filename}"

    except Exception as e:
        print(f"Error saving image: {e}")
        # Fallback or re-raise depending on strictness
        raise e
