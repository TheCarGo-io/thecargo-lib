from uuid import uuid4

from thecargo.utils.timezone import now_ny

from fastapi import HTTPException, UploadFile

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_DOC_TYPES = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_DOC_TYPES
MAX_FILE_SIZE = 10 * 1024 * 1024


def _generate_path(prefix: str, filename: str) -> str:
    now = now_ny()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    return f"{prefix}/{now.year}/{now.month:02d}/{now.day:02d}/{uuid4().hex[:12]}.{ext}"


async def save_upload(file: UploadFile, prefix: str = "uploads", allowed_types: set | None = None) -> str:
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    types = allowed_types or ALLOWED_TYPES
    if file.content_type and file.content_type not in types:
        raise HTTPException(400, f"File type not allowed: {file.content_type}")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large: max {MAX_FILE_SIZE // 1024 // 1024}MB")

    from thecargo.storage import upload_bytes
    path = _generate_path(prefix, file.filename)
    return upload_bytes(path, data, content_type=file.content_type or "application/octet-stream")


async def save_image(file: UploadFile, prefix: str = "images") -> str:
    return await save_upload(file, prefix=prefix, allowed_types=ALLOWED_IMAGE_TYPES)
