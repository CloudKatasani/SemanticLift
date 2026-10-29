"""Background pipeline runs.

Large estates take minutes to process, so the UI submits a job and polls it instead of holding an HTTP
request open. One run per project at a time; at most ``SEMLIFT_MAX_CONCURRENT_RUNS`` (default 2) runs
across all projects, the rest queue.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_pool: ThreadPoolExecutor | None = None
MAX_KEPT = 200


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=int(os.environ.get("SEMLIFT_MAX_CONCURRENT_RUNS", "2")),
                                   thread_name_prefix="semlift-run")
    return _pool


class Busy(Exception):
    pass


def active(project: str) -> dict | None:
    with _lock:
        return next((j for j in _jobs.values() if j["project"] == project and j["status"] in ("queued", "running")), None)


def submit(project: str, kind: str, user: str, fn: Callable[[], dict], run_lock: threading.Lock) -> dict:
    """fn runs in the pool while holding the project's run lock; its return value becomes job['result']."""
    with _lock:
        if any(j["project"] == project and j["status"] in ("queued", "running") for j in _jobs.values()):
            raise Busy("a run is already queued or running for this project")
        job = {"id": uuid.uuid4().hex[:12], "project": project, "kind": kind, "user": user, "status": "queued",
               "submitted": _now(), "started": None, "finished": None, "result": None, "error": None}
        _jobs[job["id"]] = job
        if len(_jobs) > MAX_KEPT:
            for jid in [k for k, v in sorted(_jobs.items(), key=lambda x: x[1]["submitted"])
                        if v["status"] in ("succeeded", "failed")][: len(_jobs) - MAX_KEPT]:
                _jobs.pop(jid, None)

    def work():
        with run_lock:
            job.update(status="running", started=_now())
            try:
                job["result"] = fn()
                job["status"] = "succeeded"
            except Exception as e:  # surfaced to the UI; full trace kept for operators
                job.update(status="failed", error=str(e) or e.__class__.__name__, trace=traceback.format_exc()[-4000:])
            job["finished"] = _now()

    _executor().submit(work)
    return public(job)


def get(job_id: str) -> dict | None:
    j = _jobs.get(job_id)
    return public(j) if j else None


def recent(project: str, limit: int = 20) -> list[dict]:
    with _lock:
        rows = [public(j) for j in _jobs.values() if j["project"] == project]
    return sorted(rows, key=lambda j: j["submitted"], reverse=True)[:limit]


def public(j: dict) -> dict:
    return {k: v for k, v in j.items() if k != "trace"}
