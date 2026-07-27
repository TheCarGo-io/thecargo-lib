import logging
import time
from functools import wraps
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

_client: Any = None
_signing_client: Any = None
_bucket: str = ""
_public_url: str = ""

MAX_RETRIES = 3
RETRY_DELAY = 1.0

_TRANSIENT = (ClientError, BotoCoreError, ConnectionError, OSError)

_NON_RETRYABLE_CODES = frozenset(
    {"NoSuchKey", "NoSuchBucket", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
)


def _client_error_code(exc: Exception) -> tuple[str, int | None]:
    if not isinstance(exc, ClientError):
        return "", None
    response = getattr(exc, "response", None) or {}
    code = str((response.get("Error") or {}).get("Code") or "")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code, status if isinstance(status, int) else None


def _is_retryable(exc: Exception) -> bool:
    code, status = _client_error_code(exc)
    if code in _NON_RETRYABLE_CODES:
        return False
    if status is not None and 400 <= status < 500:
        return False
    return True


def is_missing_object_error(exc: Exception) -> bool:
    code, status = _client_error_code(exc)
    return code == "NoSuchKey" or status == 404


def _retry(func: Any) -> Any:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except _TRANSIENT as e:
                last_exc = e
                if not _is_retryable(e):
                    logger.warning("R2 %s non-retryable error: %s", func.__name__, e)
                    raise
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY * attempt
                    logger.warning(
                        "R2 %s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        func.__name__,
                        attempt,
                        MAX_RETRIES,
                        e,
                        delay,
                    )
                    time.sleep(delay)
        logger.error("R2 %s failed after %d attempts: %s", func.__name__, MAX_RETRIES, last_exc)
        raise last_exc

    return wrapper


def _build_client(endpoint_url: str, access_key: str, secret_key: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def init_storage(
    endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False, public_url: str = ""
):
    global _client, _signing_client, _bucket, _public_url
    try:
        endpoint_url = f"{'https' if secure else 'http'}://{endpoint}"
        _client = _build_client(endpoint_url, access_key, secret_key)
        _bucket = bucket
        _public_url = (public_url or endpoint_url).rstrip("/")

        sign_host = urlparse(_public_url).netloc
        if sign_host and sign_host != urlparse(endpoint_url).netloc:
            _signing_client = _build_client(_public_url, access_key, secret_key)
            logger.info("R2 storage connected: %s/%s (presign via %s)", endpoint, bucket, sign_host)
        else:
            _signing_client = _client
            logger.info("R2 storage connected: %s/%s", endpoint, bucket)

        _ensure_bucket()
    except Exception as e:
        logger.warning("R2 storage not available: %s. File uploads disabled.", e)
        _client = None
        _signing_client = None


def _ensure_bucket():
    if _client is None:
        return
    try:
        _client.head_bucket(Bucket=_bucket)
    except ClientError as e:
        logger.warning("R2 bucket not reachable (%s): %s", _bucket, e)


@_retry
def upload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if _client is None:
        raise RuntimeError("R2 storage not initialized")
    _client.put_object(Bucket=_bucket, Key=path, Body=data, ContentType=content_type)
    return get_public_url(path)


@_retry
def upload_file(path: str, file_path: str, content_type: str = "application/octet-stream") -> str:
    if _client is None:
        raise RuntimeError("R2 storage not initialized")
    _client.upload_file(file_path, _bucket, path, ExtraArgs={"ContentType": content_type})
    return get_public_url(path)


def get_public_url(path: str) -> str:
    return f"{_public_url}/{_bucket}/{path}"


def _is_r2_host(host: str) -> bool:
    return host.endswith((".r2.dev", ".r2.cloudflarestorage.com"))


def _is_own_host(host: str) -> bool:
    own = urlparse(_public_url).netloc if _public_url else ""
    return bool(host) and (host == own or _is_r2_host(host))


def bucket_and_path_from_url(url: str) -> tuple[str, str]:
    if not url:
        return _bucket, ""
    if url.startswith(("http://", "https://")):
        parsed = urlparse(url)
        if not _is_own_host(parsed.netloc):
            return _bucket, ""
        rest = parsed.path.lstrip("/")
        head, _, key = rest.partition("/")
        return (head, key) if key else (_bucket, rest)
    path = url.lstrip("/")
    if _bucket and path.startswith(f"{_bucket}/"):
        path = path[len(_bucket) + 1 :]
    return _bucket, path


def object_path_from_url(url: str) -> str:
    return bucket_and_path_from_url(url)[1]


def is_external_url(reference: str) -> bool:
    if not reference or not reference.startswith(("http://", "https://")):
        return False
    return not _is_own_host(urlparse(reference).netloc)


@_retry
def presigned_get_url(path: str, expires_seconds: int = 600, bucket: str | None = None) -> str:
    if _signing_client is None:
        raise RuntimeError("R2 storage not initialized")
    return _signing_client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket or _bucket, "Key": path}, ExpiresIn=expires_seconds
    )


@_retry
def download_object_bytes(path: str, bucket: str | None = None) -> tuple[bytes, str]:
    if _client is None:
        raise RuntimeError("R2 storage not initialized")
    resp = _client.get_object(Bucket=bucket or _bucket, Key=path)
    data = resp["Body"].read()
    content_type = (resp.get("ContentType") or "application/octet-stream").split(";")[0]
    return data, content_type


@_retry
def delete_object(path: str, bucket: str | None = None):
    if _client is None:
        raise RuntimeError("R2 storage not initialized")
    _client.delete_object(Bucket=bucket or _bucket, Key=path)


@_retry
def object_exists(path: str, bucket: str | None = None) -> bool:
    if _client is None:
        return False
    try:
        _client.head_object(Bucket=bucket or _bucket, Key=path)
        return True
    except ClientError:
        return False
