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
                        func.__name__,
                        attempt,
                        MAX_RETRIES,
                        e,
                        delay,
                    )
                    time.sleep(delay)
        logger.error("MinIO %s failed after %d attempts: %s", func.__name__, MAX_RETRIES, last_exc)
        raise last_exc

    return wrapper


def init_storage(
    endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False, public_url: str = ""
):
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


def object_path_from_url(url: str) -> str:
    """Strip the public-URL prefix from a stored file URL.

    ``shipment_files.url`` rows hold ``{public_url}/{bucket}/{path}``.
    For presigning we need just ``{path}``.
    """
    if not url:
        return ""
    if _public_url and url.startswith(_public_url):
        url = url[len(_public_url) :]
    url = url.lstrip("/")
    if _bucket and url.startswith(f"{_bucket}/"):
        url = url[len(_bucket) + 1 :]
    return url


@_retry
def presigned_get_url(path: str, expires_seconds: int = 600) -> str:
    """Time-limited GET URL for a private-bucket object.

    The URL embeds an HMAC signature so the browser can fetch the
    bytes directly without server-side proxying. Default 10-minute
    expiry covers a click-to-download flow without leaving long-lived
    tokens in browser history.
    """
    if _client is None:
        raise RuntimeError("MinIO not initialized")
    from datetime import timedelta

    return _client.presigned_get_object(_bucket, path, expires=timedelta(seconds=expires_seconds))


@_retry
def download_object_bytes(path: str) -> tuple[bytes, str]:
    """Server-side fetch of an object's bytes + content-type.

    The bucket is private, so a non-presigned ``shipment_files.url``
    cannot be re-fetched over plain HTTP — ``httpx.get(url)`` returns
    ``AccessDenied``. This helper bypasses the URL layer entirely and
    pulls bytes directly through the authenticated MinIO client.

    Used by the email dispatcher so private attachments still embed
    cleanly in outbound mail without exposing a presigned URL to the
    recipient (the bytes ride along inside the MIME envelope).
    """
    if _client is None:
        raise RuntimeError("MinIO not initialized")
    resp = _client.get_object(_bucket, path)
    try:
        data = resp.read()
        content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0]
        return data, content_type
    finally:
        resp.close()
        resp.release_conn()


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
