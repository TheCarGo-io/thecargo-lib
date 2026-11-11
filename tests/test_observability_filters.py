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


def test_the_ai_agent_integration_stays_off(monkeypatch):
    import sys
    import types

    import sentry_sdk

    from thecargo import observability

    class PydanticAIIntegration:
        pass

    module = types.ModuleType("sentry_sdk.integrations.pydantic_ai")
    module.PydanticAIIntegration = PydanticAIIntegration
    seen = {}
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.pydantic_ai", module)
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: seen.update(options))
    monkeypatch.setenv("SENTRY_DSN", "https://key@example.invalid/1")
    monkeypatch.setattr(observability, "_initialized", False)

    assert observability.init_sentry()
    assert [type(off) for off in seen["disabled_integrations"]] == [PydanticAIIntegration]


def test_a_service_without_the_ai_agent_library_starts_error_tracking_as_before(monkeypatch):
    import sys

    import sentry_sdk

    from thecargo import observability

    seen = {}
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.pydantic_ai", None)
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: seen.update(options))
    monkeypatch.setenv("SENTRY_DSN", "https://key@example.invalid/1")
    monkeypatch.setattr(observability, "_initialized", False)

    assert observability.init_sentry()
    assert "disabled_integrations" not in seen
