import logging
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_client: Any = None
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
    global _client, _bucket, _public_url
    try:
        endpoint_url = f"{'https' if secure else 'http'}://{endpoint}"
        _client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        _bucket = bucket
        _public_url = (public_url or endpoint_url).rstrip("/")

        try:
            _client.head_bucket(Bucket=_bucket)
        except ClientError as exc:
            logger.warning("Public R2 bucket not reachable (%s): %s", _bucket, exc)
        logger.info("Public R2 storage connected: %s", _bucket)
    except Exception as exc:
        logger.warning("Public R2 not available: %s. Public uploads disabled.", exc)
        _client = None


def upload_public_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if _client is None:
        raise RuntimeError("Public R2 not initialized")
    _client.put_object(Bucket=_bucket, Key=path, Body=data, ContentType=content_type)
    return f"{_public_url}/{path}"


def delete_public_object_from_url(url: str | None) -> None:
    if not url or _client is None:
        return
    if not url.startswith(_public_url):
        return
    key = url[len(_public_url) :].lstrip("/").split("?")[0]
    if not key:
        return
    try:
        _client.delete_object(Bucket=_bucket, Key=key)
    except ClientError as exc:
        logger.warning("Public R2 delete failed for %s: %s", key, exc)
