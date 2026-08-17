import asyncio
import logging

from thecargo.observability import _enrich_event, _is_cancellation


def _record(exc_info) -> logging.LogRecord:
    return logging.LogRecord(
        name="sqlalchemy.pool.impl.AsyncAdaptedQueuePool",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception terminating connection %r",
        args=None,
        exc_info=exc_info,
    )


def _exc_info(exc: BaseException):
    return (type(exc), exc, None)


def test_cancelled_error_is_dropped():
    exc = asyncio.CancelledError("Cancelled via cancel scope 706d2ca547d0")
    assert _enrich_event({}, {"log_record": _record(_exc_info(exc))}) is None


def test_cancelled_error_wrapped_in_cause_is_dropped():
    cancelled = asyncio.CancelledError()
    wrapper = RuntimeError("teardown failed")
    wrapper.__cause__ = cancelled
    assert _enrich_event({}, {"log_record": _record(_exc_info(wrapper))}) is None


def test_capture_exception_hint_is_dropped():
    exc = asyncio.CancelledError()
    assert _enrich_event({}, {"exc_info": _exc_info(exc)}) is None


def test_log_without_exc_info_is_dropped():
    assert _enrich_event({}, {"log_record": _record(None)}) is None


def test_real_error_is_kept():
    exc = ValueError("boom")
    event = _enrich_event({}, {"log_record": _record(_exc_info(exc))})
    assert event is not None
    assert event["tags"]["service"]


def test_cancellation_chain_tolerates_cycles():
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__context__ = b
    b.__context__ = a
    assert _is_cancellation(a) is False
