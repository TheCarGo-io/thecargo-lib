import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from celery import Celery
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool, QueuePool
from starlette.middleware.base import BaseHTTPMiddleware

from thecargo import metrics
from thecargo.metrics import MetricsMiddleware, QueueLengthCollector, setup_metrics

LIB_ROOT = Path(__file__).resolve().parents[1]
SHIPMENT_ROUTE = "/shipments/{shipment_id}"


def _sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _app(**pools) -> FastAPI:
    app = FastAPI()

    @app.get(SHIPMENT_ROUTE)
    async def get_shipment(shipment_id: int) -> dict:
        if shipment_id == 0:
            raise HTTPException(status_code=404)
        return {"id": shipment_id}

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("boom")

    setup_metrics(app, **pools)
    return app


def _run_isolated(script: str, tmp_path: Path, **env) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env={**os.environ, "PYTHONPATH": str(LIB_ROOT), "TMPDIR": str(tmp_path), **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_requests_are_labelled_by_route_template_not_raw_path():
    client = TestClient(_app())
    ok = {"method": "GET", "route": SHIPMENT_ROUTE, "status": "200"}
    missing = {**ok, "status": "404"}
    before_ok = _sample("http_requests_total", **ok)
    before_missing = _sample("http_requests_total", **missing)
    before_duration = _sample("http_request_duration_seconds_count", **ok)

    client.get("/shipments/41")
    client.get("/shipments/42")
    client.get("/shipments/0")

    assert _sample("http_requests_total", **ok) - before_ok == 2
    assert _sample("http_requests_total", **missing) - before_missing == 1
    assert _sample("http_request_duration_seconds_count", **ok) - before_duration == 2
    assert REGISTRY.get_sample_value("http_requests_total", {**ok, "route": "/shipments/41"}) is None


def test_unrouted_paths_and_unknown_methods_share_bounded_labels():
    client = TestClient(_app())
    unmatched = {"method": "GET", "route": metrics.UNMATCHED_ROUTE, "status": "404"}
    other = {"method": "OTHER", "route": SHIPMENT_ROUTE, "status": "405"}
    before_unmatched = _sample("http_requests_total", **unmatched)
    before_other = _sample("http_requests_total", **other)

    client.get("/wp-admin/one")
    client.get("/wp-admin/two")
    client.request("PROPFIND", "/shipments/1")

    assert _sample("http_requests_total", **unmatched) - before_unmatched == 2
    assert _sample("http_requests_total", **other) - before_other == 1


def test_an_escaping_exception_counts_as_a_500_and_by_type():
    client = TestClient(_app(), raise_server_exceptions=False)
    failed = {"method": "GET", "route": "/boom", "status": "500"}
    raised = {"method": "GET", "route": "/boom", "exception": "RuntimeError"}
    before_failed = _sample("http_requests_total", **failed)
    before_raised = _sample("http_exceptions_total", **raised)

    assert client.get("/boom").status_code == 500

    assert _sample("http_requests_total", **failed) - before_failed == 1
    assert _sample("http_exceptions_total", **raised) - before_raised == 1


def test_metrics_endpoint_is_served_directly_and_hidden_behind_the_proxy():
    client = TestClient(_app())
    client.get("/shipments/7")

    direct = client.get("/metrics")
    assert direct.status_code == 200
    assert direct.headers["content-type"].startswith("text/plain")
    assert 'http_requests_total{method="GET",route="/shipments/{shipment_id}",status="200"}' in direct.text

    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
        assert client.get("/metrics", headers={header: "203.0.113.9"}).status_code == 404


def test_metrics_middleware_is_pure_asgi_and_outermost():
    app = _app()

    assert app.user_middleware[0].cls is MetricsMiddleware
    assert not any(issubclass(m.cls, BaseHTTPMiddleware) for m in app.user_middleware)


def test_pool_gauges_follow_checked_out_connections(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/pool.db", poolclass=QueuePool, pool_size=2, max_overflow=3)
    client = TestClient(_app(gauge_pool=engine))
    held = [engine.connect() for _ in range(3)]

    client.get("/metrics")
    assert _sample("db_pool_size", pool="gauge_pool") == 2
    assert _sample("db_pool_checked_out", pool="gauge_pool") == 3
    assert _sample("db_pool_overflow", pool="gauge_pool") == 1

    for conn in held:
        conn.close()
    client.get("/shipments/1")
    assert _sample("db_pool_checked_out", pool="gauge_pool") == 0
    assert _sample("db_pool_overflow", pool="gauge_pool") == 0


def test_a_pool_without_a_size_is_skipped(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/null.db", poolclass=NullPool)
    client = TestClient(_app(null_pool=engine))

    assert client.get("/metrics").status_code == 200
    assert REGISTRY.get_sample_value("db_pool_size", {"pool": "null_pool"}) is None


def test_task_duration_is_recorded_by_task_name_and_state():
    app = Celery("metrics_test", broker="memory://")
    metrics.install_celery_metrics()

    @app.task(name="metrics_test.ok")
    def ok() -> int:
        return 1

    @app.task(name="metrics_test.fail")
    def fail() -> None:
        raise ValueError("nope")

    succeeded = {"task": "metrics_test.ok", "state": "SUCCESS"}
    failed = {"task": "metrics_test.fail", "state": "FAILURE"}
    before_succeeded = _sample("celery_task_duration_seconds_count", **succeeded)
    before_failed = _sample("celery_task_duration_seconds_count", **failed)

    ok.apply()
    fail.apply()

    assert _sample("celery_task_duration_seconds_count", **succeeded) - before_succeeded == 1
    assert _sample("celery_task_duration_seconds_count", **failed) - before_failed == 1


def test_published_tasks_are_counted_by_name():
    app = Celery("metrics_publish", broker="memory://")
    metrics.install_celery_metrics()
    before = _sample("celery_tasks_published_total", task="metrics_publish.job")

    app.send_task("metrics_publish.job", queue="metrics_publish")
    app.send_task("metrics_publish.job", queue="metrics_publish")

    assert _sample("celery_tasks_published_total", task="metrics_publish.job") - before == 2


def test_queue_length_is_read_from_the_broker_and_missing_queues_are_empty():
    app = Celery("metrics_queue", broker="memory://")
    app.send_task("metrics_queue.job", queue="metrics_depth")
    app.send_task("metrics_queue.job", queue="metrics_depth")

    (family,) = QueueLengthCollector(app, ["metrics_depth", "metrics_never_declared"]).collect()

    assert {s.labels["queue"]: s.value for s in family.samples} == {
        "metrics_depth": 2,
        "metrics_never_declared": 0,
    }


def test_an_unreachable_broker_leaves_queue_length_empty_instead_of_failing_the_scrape():
    app = Celery("metrics_down", broker="redis://127.0.0.1:1/0")

    (family,) = QueueLengthCollector(app, ["anything"]).collect()

    assert family.samples == []


def test_recycled_pool_children_reuse_their_slot_files(tmp_path):
    result = _run_isolated(
        """
        import json, os
        from types import SimpleNamespace
        from billiard.process import current_process
        from thecargo import metrics

        metrics._on_worker_init()
        path = os.environ["PROMETHEUS_MULTIPROC_DIR"]

        def child(index, task_id):
            pid = os.fork()
            if pid == 0:
                current_process().index = index
                metrics._on_task_prerun(task_id=task_id)
                metrics._on_task_postrun(task_id=task_id, task=SimpleNamespace(name="demo.task"), state="SUCCESS")
                os._exit(0)
            os.waitpid(pid, 0)

        child(0, "a")
        child(0, "b")
        child(1, "c")

        count = metrics.registry().get_sample_value(
            "celery_task_duration_seconds_count", {"task": "demo.task", "state": "SUCCESS"}
        )
        print(json.dumps({"count": count, "files": sorted(os.listdir(path))}))
        """,
        tmp_path,
    )

    assert result == {"count": 3.0, "files": ["histogram_pool0.db", "histogram_pool1.db"]}


def test_web_workers_share_one_directory_and_dead_workers_drop_out_of_live_gauges(tmp_path):
    result = _run_isolated(
        """
        import json, os
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from thecargo import metrics

        app = FastAPI()

        @app.get("/ping")
        async def ping():
            return {}

        metrics.setup_metrics(app)
        client = TestClient(app)
        client.get("/ping")
        exposed = 'http_requests_total{method="GET",route="/ping",status="200"} 1.0' in client.get("/metrics").text
        path = os.environ["PROMETHEUS_MULTIPROC_DIR"]

        pid = os.fork()
        if pid == 0:
            metrics.DB_POOL_SIZE.labels("main").set(5)
            os._exit(0)
        os.waitpid(pid, 0)
        metrics.DB_POOL_SIZE.labels("main").set(2)

        def live_size():
            return metrics.registry().get_sample_value("db_pool_size", {"pool": "main"})

        with_dead = live_size()
        metrics.forget_dead_processes(path)
        print(json.dumps({
            "exposed": exposed,
            "dir": os.path.basename(path),
            "with_dead": with_dead,
            "after_forget": live_size(),
        }))
        """,
        tmp_path,
        WEB_CONCURRENCY="2",
    )

    assert result == {
        "exposed": True,
        "dir": f"thecargo-metrics-{os.getpid()}",
        "with_dead": 7.0,
        "after_forget": 2.0,
    }
