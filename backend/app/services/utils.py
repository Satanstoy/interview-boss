import base64

# Re-export from db.utils for backward compatibility
from app.db.utils import normalize_category, _extract_url_signature  # noqa: F401


def encode_image(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode('utf-8')
