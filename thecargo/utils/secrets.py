import os


def read_secret(key: str, default: str = "") -> str:
    """Read a value from a Docker secret file or fall back to env var.

    Docker Secrets mount files at /run/secrets/<name>.
    If <KEY>_FILE env var is set and the file exists, return its contents.
    Otherwise return the env var <KEY> or the default.
    """
    file_path = os.environ.get(f"{key}_FILE")
    if file_path and os.path.isfile(file_path):
        with open(file_path) as f:
            return f.read().strip()
    return os.environ.get(key, default)
