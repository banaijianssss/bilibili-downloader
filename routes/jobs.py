"""下载任务、历史、SSE。"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from config import MEDIA_MODES
from jobs import db as jobs_db
from jobs import queue as job_queue
from media.ytdlp_util import normalize_media, safe_name
from settings_store import load_history

router = APIRouter()


def _bool_opt(body: dict, key: str, default: bool) -> bool:
    if key not in body:
        return default
    v = body[key]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("0", "false", "no", "off", ""):
        return False
    return True


def _parse_pages(body: dict, default_page: int = 1) -> list[int]:
    if body.get("all_pages"):
        # pages list from body or need caller to pass page_count
        pages = body.get("pages")
        if isinstance(pages, list) and pages:
            return [int(p) for p in pages]
        page_count = int(body.get("page_count") or body.get("total_pages") or 0)
        if page_count > 0:
            return list(range(1, page_count + 1))
        raise HTTPException(400, "全部下载需要提供 pages 列表或 page_count")
    if "pages" in body and isinstance(body["pages"], list) and body["pages"]:
        return sorted({int(p) for p in body["pages"] if int(p) >= 1})
    return [int(body.get("page") or default_page)]


@router.post("/api/download")
async def start_download(body: dict) -> dict:
    bvid = str(body.get("bvid") or "").strip()
    title = safe_name(str(body.get("title") or bvid))
    media = normalize_media(body.get("media") or body.get("type") or body.get("mode"))
    format_id = str(body.get("format_id") or body.get("format") or "").strip() or None
    if format_id and not re.fullmatch(r"[0-9A-Za-z._+-]+", format_id):
        raise HTTPException(400, "无效的 format_id")
    if not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
        raise HTTPException(400, "无效的 BV 号")

    subs = _bool_opt(body, "subs", True)
    cover = _bool_opt(body, "cover", True)
    pages = _parse_pages(body)

    jobs = []
    for page in pages:
        job = job_queue.enqueue(
            bvid=bvid,
            page=page,
            title=title,
            media=media,
            media_label=MEDIA_MODES[media]["label"],
            format_id=format_id,
            subs=subs,
            cover=cover,
        )
        jobs.append(job)

    if len(jobs) == 1:
        return jobs[0]
    return {"items": jobs, "count": len(jobs)}


@router.get("/api/jobs")
async def jobs() -> dict:
    return {"items": jobs_db.list_jobs()}


@router.get("/api/jobs/stream")
async def jobs_stream() -> StreamingResponse:
    return StreamingResponse(
        job_queue.sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/jobs/{job_id}")
async def job_detail(job_id: str) -> dict:
    job = jobs_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@router.post("/api/jobs/{job_id}/cancel")
async def job_cancel(job_id: str) -> dict:
    job = job_queue.cancel_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@router.post("/api/jobs/{job_id}/retry")
async def job_retry(job_id: str) -> dict:
    job = job_queue.retry_job(job_id)
    if not job:
        raise HTTPException(400, "任务不存在或当前状态不可重试")
    return job


@router.get("/api/history")
async def history() -> dict:
    return {"items": load_history()}


@router.get("/api/files/{job_id}")
async def download_file(job_id: str) -> FileResponse:
    history_items = load_history()
    match = next((x for x in history_items if x.get("id") == job_id), None)
    path = ""
    if match:
        path = match.get("path") or ""
    if not path:
        job = jobs_db.get_job(job_id)
        path = (job or {}).get("file") or ""
    if not path or not Path(path).exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=Path(path).name)
