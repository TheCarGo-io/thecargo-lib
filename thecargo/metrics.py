import logging
import os
import shutil
import tempfile
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    generate_latest,
    multiprocess,
    start_http_server,
    values,
)
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

disable_created_metrics()

UNMATCHED_ROUTE = "unmatched"
CELERY_METRICS_PORT = 9808

_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by route template and status",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration by route template and status",
    ("method", "route", "status"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10, 30),
)
HTTP_EXCEPTIONS = Counter(
    "http_exceptions_total",
    "Exceptions that escaped the app while serving a request",
    ("method", "route", "exception"),
)

DB_POOL_SIZE = Gauge("db_pool_size", "Configured connection pool size", ("pool",), multiprocess_mode="livesum")
DB_POOL_CHECKED_OUT = Gauge(
    "db_pool_checked_out", "Connections checked out of the pool", ("pool",), multiprocess_mode="livesum"
)
DB_POOL_OVERFLOW = Gauge(
    "db_pool_overflow", "Connections open beyond the pool size", ("pool",), multiprocess_mode="livesum"
)

CELERY_TASK_DURATION = Histogram(
    "celery_task_duration_seconds",
    "Celery task run time by final state",
    ("task", "state"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
)
CELERY_TASKS_PUBLISHED = Counter(
    "celery_tasks_published_total",
    "Celery tasks published by this process",
    ("task",),
)

_task_started: dict[str, float] = {}


def _route(scope: dict) -> str:
    route = scope.get("route")
    return route.path if route is not None else UNMATCHED_ROUTE


def refresh_pool_metrics(pools: dict) -> None:
    for name, engine in pools.items():
        pool = engine.pool
        if isinstance(pool, QueuePool):
            DB_POOL_SIZE.labels(name).set(pool.size())
            DB_POOL_CHECKED_OUT.labels(name).set(pool.checkedout())
            DB_POOL_OVERFLOW.labels(name).set(max(pool.overflow(), 0))


class MetricsMiddleware:
    def __init__(self, app, pools: dict):
        self.app = app
        self.pools = pools

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"] if scope["method"] in _METHODS else "OTHER"
        status = 500

        async def send_with_status(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_status)
        except Exception as exc:
            HTTP_EXCEPTIONS.labels(method, _route(scope), type(exc).__name__).inc()
            raise
        finally:
            route = _route(scope)
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_DURATION.labels(method, route, str(status)).observe(time.perf_counter() - started)
            refresh_pool_metrics(self.pools)


def registry() -> CollectorRegistry:
    path = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not path:
        return REGISTRY
    collected = CollectorRegistry()
    multiprocess.MultiProcessCollector(collected, path)
    return collected


def use_multiprocess(path: str, process_identifier=os.getpid) -> None:
    os.makedirs(path, exist_ok=True)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = path
    values.ValueClass = values.MultiProcessValue(process_identifier)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def forget_dead_processes(path: str) -> None:
    for name in os.listdir(path):
        pid = name.removesuffix(".db").rsplit("_", 1)[-1]
        if name.startswith("gauge_live") and pid.isdigit() and not _alive(int(pid)):
            multiprocess.mark_process_dead(int(pid), path)


def setup_metrics(app: FastAPI, **pools) -> None:
    if int(os.environ.get("WEB_CONCURRENCY") or 1) > 1:
        path = os.path.join(tempfile.gettempdir(), f"thecargo-metrics-{os.getppid()}")
        use_multiprocess(path)
        forget_dead_processes(path)

    app.add_middleware(MetricsMiddleware, pools=pools)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        if any(header in request.headers for header in _PROXY_HEADERS):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        refresh_pool_metrics(pools)
        return Response(generate_latest(registry()), media_type=CONTENT_TYPE_LATEST)


class QueueLengthCollector:
    def __init__(self, app, queues: list[str]):
        self.app = app
        self.queues = queues

    def collect(self):
        family = GaugeMetricFamily("celery_queue_length", "Messages waiting in a Celery queue", labels=("queue",))
        try:
            with self.app.pool.acquire(block=True, timeout=5) as conn:
                try:
                    lengths = _queue_lengths(conn, self.queues)
                except conn.connection_errors:
                    conn.collect()
                    lengths = _queue_lengths(conn, self.queues)
            for queue, length in lengths:
                family.add_metric((queue,), length)
        except Exception as exc:
            logger.warning("celery queue length unavailable: %s", exc)
        yield family


def _queue_lengths(conn, queues: list[str]) -> list[tuple[str, int]]:
    return [(queue, _queue_length(conn, queue)) for queue in queues]


def _queue_length(conn, queue: str) -> int:
    channel = conn.channel()
    try:
        return channel.queue_declare(queue=queue, passive=True).message_count
    except conn.channel_errors:
        return 0
    finally:
        channel.close()


def _serve(collected: CollectorRegistry) -> None:
    try:
        start_http_server(CELERY_METRICS_PORT, registry=collected)
    except OSError as exc:
        logger.warning("celery metrics port %s unavailable: %s", CELERY_METRICS_PORT, exc)
        return
    logger.info("celery metrics served on :%s/metrics", CELERY_METRICS_PORT)


def _on_worker_init(**_kwargs) -> None:
    from billiard.process import current_process

    def pool_process_id() -> str:
        index = getattr(current_process(), "index", None)
        return str(os.getpid()) if index is None else f"pool{index}"

    path = os.path.join(tempfile.gettempdir(), f"thecargo-metrics-celery-{os.getpid()}")
    shutil.rmtree(path, ignore_errors=True)
    use_multiprocess(path, pool_process_id)


def _on_worker_ready(sender, **_kwargs) -> None:
    collected = registry()
    collected.register(QueueLengthCollector(sender.app, sorted(sender.app.amqp.queues.consume_from)))
    _serve(collected)


def _on_beat_init(**_kwargs) -> None:
    _serve(registry())


def _on_task_prerun(task_id, **_kwargs) -> None:
    _task_started[task_id] = time.perf_counter()


def _on_task_postrun(task_id, task, state, **_kwargs) -> None:
    started = _task_started.pop(task_id)
    CELERY_TASK_DURATION.labels(task.name, state).observe(time.perf_counter() - started)


def _on_task_published(sender, **_kwargs) -> None:
    CELERY_TASKS_PUBLISHED.labels(sender).inc()


def install_celery_metrics() -> None:
    from celery import signals

    signals.celeryd_init.connect(_on_worker_init, weak=False)
    signals.worker_ready.connect(_on_worker_ready, weak=False)
    signals.beat_init.connect(_on_beat_init, weak=False)
    signals.task_prerun.connect(_on_task_prerun, weak=False)
    signals.task_postrun.connect(_on_task_postrun, weak=False)
    signals.after_task_publish.connect(_on_task_published, weak=False)
