import os
import qrcode
from app.core.config import settings


QR_CODE_DIR = settings.static_dir / "qrcodes"
STATIC_URL_PREFIX = "/static/qrcodes"


def generate_and_save_qr(data: str, filename: str) -> str:
    """
    Generates a QR code for the given data, saves it to the filesystem,
    and returns the relative URL path.
    """
    # Ensure directory exists
    os.makedirs(QR_CODE_DIR, exist_ok=True)

    # Generate QR
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Save file
    file_path = QR_CODE_DIR / f"{filename}.png"
    img.save(file_path)

    # Return web-accessible URL
    return f"{settings.public_url}{STATIC_URL_PREFIX}/{filename}.png"
