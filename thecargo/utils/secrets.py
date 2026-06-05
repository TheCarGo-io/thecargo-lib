import os


def read_secret(key: str, default: str = "") -> str:
    file_path = os.environ.get(f"{key}_FILE")
    if file_path and os.path.isfile(file_path):
        with open(file_path) as f:
            return f.read().strip()
    return os.environ.get(key, default)
