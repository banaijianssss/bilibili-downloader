"""下载工作队列：最多同时 2 个；SSE 事件广播。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from config import MAX_CONCURRENT_DOWNLOADS
from jobs import db as jobs_db

_worker_task: asyncio.Task | None = None
_wake = asyncio.Event()
_subscribers: set[asyncio.Queue] = set()
_running = False


def notify_job_update(job_id: str) -> None:
    job = jobs_db.get_job(job_id)
    if not job:
        return
    payload = {"type": "job", "job": job}
    dead: list[asyncio.Queue] = []
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def wake_worker() -> None:
    _wake.set()


async def _worker_loop() -> None:
    global _running
    _running = True
    from jobs.runner import run_download

    while _running:
        # 填满并发槽
        while jobs_db.count_active() < MAX_CONCURRENT_DOWNLOADS:
            job = jobs_db.claim_next_queued()
            if not job:
                break
            notify_job_update(job["id"])
            asyncio.create_task(_safe_run(run_download, job["id"]))
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass


async def _safe_run(fn, job_id: str) -> None:
    try:
        await fn(job_id)
    finally:
        wake_worker()


async def start_worker() -> None:
    global _worker_task
    jobs_db.init_db()
    n = jobs_db.recover_on_startup()
    if n:
        # 把 interrupted 的任务留着让用户重试；queued 自动继续
        pass
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())
    wake_worker()


async def stop_worker() -> None:
    global _running, _worker_task
    _running = False
    wake_worker()
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except (asyncio.CancelledError, Exception):
            pass
    _worker_task = None


def enqueue(
    *,
    bvid: str,
    page: int = 1,
    title: str = "",
    media: str = "muxed",
    media_label: str = "",
    format_id: str | None = None,
    subs: bool = True,
    cover: bool = True,
) -> dict:
    job = jobs_db.create_job(
        bvid=bvid,
        page=page,
        title=title,
        media=media,
        media_label=media_label,
        format_id=format_id,
        subs=subs,
        cover=cover,
    )
    wake_worker()
    notify_job_update(job["id"])
    return job


def cancel_job(job_id: str) -> dict | None:
    job = jobs_db.get_job(job_id)
    if not job:
        return None
    if job["status"] in ("done", "cancelled"):
        return job
    if job["status"] == "queued":
        updated = jobs_db.update_job(job_id, status="cancelled", error="任务已取消")
        notify_job_update(job_id)
        return updated
    # running / downloading：标记取消，runner 在 hook 中检测
    updated = jobs_db.update_job(job_id, status="cancelled", error="任务已取消")
    notify_job_update(job_id)
    return updated


def retry_job(job_id: str) -> dict | None:
    updated = jobs_db.reset_for_retry(job_id)
    if updated:
        wake_worker()
        notify_job_update(job_id)
    return updated


async def sse_event_generator():
    q = subscribe()
    try:
        # 初始快照
        items = jobs_db.list_jobs(100)
        yield _sse({"type": "snapshot", "items": items})
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=15.0)
                yield _sse(payload)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        unsubscribe(q)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
