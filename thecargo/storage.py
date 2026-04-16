import io
import logging
import time
from functools import wraps
from typing import Any

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import MaxRetryError

logger = logging.getLogger(__name__)

_client: Minio | None = None
_bucket: str = ""
_public_url: str = ""

MAX_RETRIES = 3
RETRY_DELAY = 1.0


def _retry(func: Any) -> Any:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except (S3Error, MaxRetryError, ConnectionError, OSError) as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY * attempt
                    logger.warning(
                        "MinIO %s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        func.__name__, attempt, MAX_RETRIES, e, delay,
                    )
                    time.sleep(delay)
        logger.error("MinIO %s failed after %d attempts: %s", func.__name__, MAX_RETRIES, last_exc)
        raise last_exc
    return wrapper


def init_storage(endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False, public_url: str = ""):
    global _client, _bucket, _public_url
    try:
        _client = Minio(endpoint=endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        _bucket = bucket
        _public_url = public_url or f"{'https' if secure else 'http'}://{endpoint}"
        _ensure_bucket()
        logger.info("MinIO connected: %s/%s", endpoint, bucket)
    except Exception as e:
        logger.warning("MinIO not available: %s. File uploads disabled.", e)
        _client = None


def _ensure_bucket():
    if _client is None:
        return
    try:
        if not _client.bucket_exists(_bucket):
            _client.make_bucket(_bucket)
            logger.info("Created MinIO bucket: %s", _bucket)
    except S3Error as e:
        logger.error("MinIO bucket check failed: %s", e)
        raise


@_retry
def upload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if _client is None:
        raise RuntimeError("MinIO not initialized")
    _client.put_object(
        bucket_name=_bucket,
        object_name=path,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return get_public_url(path)


@_retry
def upload_file(path: str, file_path: str, content_type: str = "application/octet-stream") -> str:
    if _client is None:
        raise RuntimeError("MinIO not initialized")
    _client.fput_object(
        bucket_name=_bucket,
        object_name=path,
        file_path=file_path,
        content_type=content_type,
    )
    return get_public_url(path)


def get_public_url(path: str) -> str:
    return f"{_public_url}/{_bucket}/{path}"


@_retry
def delete_object(path: str):
    if _client is None:
        raise RuntimeError("MinIO not initialized")
    _client.remove_object(_bucket, path)


@_retry
def object_exists(path: str) -> bool:
    if _client is None:
        return False
    try:
        _client.stat_object(_bucket, path)
        return True
    except S3Error:
        return False
