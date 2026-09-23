from __future__ import annotations


def redact_credentials(url: str) -> str:
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"
