import logging
import threading
import time

from botocore.exceptions import EndpointConnectionError

from thecargo import public_storage, storage


class _SlowR2:
    def __init__(self, delay: float = 0.0, error: Exception | None = None):
        self.delay = delay
        self.error = error
        self.checked = threading.Event()

    def head_bucket(self, Bucket: str) -> None:
        time.sleep(self.delay)
        self.checked.set()
        if self.error is not None:
            raise self.error


def _unreachable() -> EndpointConnectionError:
    return EndpointConnectionError(endpoint_url="https://r2.invalid")


def test_storage_init_does_not_wait_for_the_bucket_check(monkeypatch):
    r2 = _SlowR2(delay=2.0)
    monkeypatch.setattr(storage, "_build_client", lambda *args, **kwargs: r2)

    started = time.perf_counter()
    storage.init_storage("r2.invalid", "key", "secret", "bucket", secure=True)

    assert time.perf_counter() - started < 0.5
    assert storage._client is r2


def test_an_unreachable_bucket_keeps_storage_enabled(monkeypatch, caplog):
    r2 = _SlowR2(error=_unreachable())
    monkeypatch.setattr(storage, "_build_client", lambda *args, **kwargs: r2)

    with caplog.at_level(logging.WARNING, logger=storage.__name__):
        storage.init_storage("r2.invalid", "key", "secret", "bucket", secure=True)
        assert r2.checked.wait(2)
        time.sleep(0.05)

    assert storage._client is r2
    assert "R2 bucket not reachable (bucket)" in caplog.text


def test_public_storage_init_does_not_wait_and_survives_an_unreachable_bucket(monkeypatch, caplog):
    r2 = _SlowR2(delay=1.0, error=_unreachable())
    monkeypatch.setattr(public_storage.boto3, "client", lambda *args, **kwargs: r2)

    with caplog.at_level(logging.WARNING, logger=public_storage.__name__):
        started = time.perf_counter()
        public_storage.init_public_storage("r2.invalid", "key", "secret", "public", secure=True)
        assert time.perf_counter() - started < 0.5
        assert r2.checked.wait(3)
        time.sleep(0.05)

    assert public_storage._client is r2
    assert "Public R2 bucket not reachable (public)" in caplog.text
