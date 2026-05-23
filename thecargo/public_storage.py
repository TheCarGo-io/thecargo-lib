"""Public-bucket MinIO helper for anonymously readable assets.

The primary :mod:`thecargo.storage` module uses a single private bucket —
URLs it returns require a presigned signature to fetch, which doesn't
work for ``<img src=...>`` in customer-facing pages. Some assets (company
logos, payment-method QR codes, public marketing images) need anonymous
read so a sign page, contract PDF, payment form, or external partner can
render them directly. This helper maintains a separate MinIO client bound
to a bucket whose policy allows anonymous ``GetObject`` for everything
under it.

Each service that needs public assets calls :func:`init_public_storage`
once at startup pointed at the same shared public bucket.
"""

import io
import json
import logging
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

_client: Minio | None = None
_bucket: str = ""
_public_url: str = ""


def init_public_storage(
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    secure: bool = False,
    public_url: str = "",
) -> None:
    """Connect to MinIO, create the public bucket if missing, and ensure
    its policy grants anonymous ``s3:GetObject`` on every object.

    Idempotent — safe to call on every service start. Failures are logged
    and swallowed so a MinIO outage at boot can't crash the process before
    the rest of the app comes up.
    """
    global _client, _bucket, _public_url
    try:
        _client = Minio(endpoint=endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        _bucket = bucket
        _public_url = public_url or f"{'https' if secure else 'http'}://{endpoint}"

        if not _client.bucket_exists(_bucket):
            _client.make_bucket(_bucket)
            logger.info("Created public MinIO bucket: %s", _bucket)

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{_bucket}/*"],
                }
            ],
        }
        _client.set_bucket_policy(_bucket, json.dumps(policy))
        logger.info("Public MinIO bucket policy applied: %s", _bucket)
    except Exception as exc:
        logger.warning("Public MinIO not available: %s. Public uploads disabled.", exc)
        _client = None


def upload_public_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Push bytes to the public bucket and return the anonymously fetchable URL."""
    if _client is None:
        raise RuntimeError("Public MinIO not initialized")
    _client.put_object(
        bucket_name=_bucket,
        object_name=path,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return f"{_public_url}/{_bucket}/{path}"


def delete_public_object_from_url(url: str | None) -> None:
    """Best-effort removal of a previously stored object given its public URL.

    Used when a new asset replaces an old one so MinIO doesn't accumulate
    orphans. Mismatches (URL from another bucket, malformed URL, already
    deleted) are swallowed — cleanup is advisory, not a correctness
    requirement.
    """
    if not url or _client is None:
        return
    parsed = urlparse(url)
    expected_prefix = f"/{_bucket}/"
    if not parsed.path.startswith(expected_prefix):
        return
    key = parsed.path[len(expected_prefix) :]
    if not key:
        return
    try:
        _client.remove_object(_bucket, key)
    except S3Error as exc:
        logger.warning("Public MinIO delete failed for %s: %s", key, exc)
