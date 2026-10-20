"""下载执行与可读错误映射。"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from config import MEDIA_MODES
from jobs import db as jobs_db
from jobs.queue import notify_job_update
from media.ytdlp_util import (
    download_opts_for,
    downloads_dir,
    find_ffmpeg,
    resolve_download_path,
    video_url,
)
from settings_store import append_history


def friendly_error(exc: BaseException) -> str:
    msg = str(exc) or exc.__class__.__name__
    low = msg.lower()
    patterns = [
        (r"ffmpeg.*(not found|unavailable|未找到)|no such file.*ffmpeg", "未检测到 FFmpeg，无法封装音视频。请安装 FFmpeg 或把 ffmpeg.exe 放到本目录。"),
        (r"premium|vip|大会员|付费|会员专享|login.?required|http.?error.?403", "需要登录或大会员权限才能下载该清晰度。请扫码登录后重试。"),
        (r"geo.?restrict|地区|region|not available in your", "该视频有地区限制，当前网络无法下载。"),
        (r"timed?\s*out|timeout|connection.*(reset|aborted|refused)", "网络超时或连接中断，请检查网络后重试。"),
        (r"unable to extract|unsupported url|no video formats|解析失败", "视频解析失败，链接可能无效或接口变更。"),
        (r"http.?error.?412|-412|风控", "请求被风控拦截，请稍后重试或重新登录。"),
        (r"cancelled|cancel", "任务已取消。"),
        (r"disk|no space|errno 28", "磁盘空间不足，请清理后重试。"),
        (r"permission|access is denied|errno 13", "写入文件失败：权限不足。"),
    ]
    for pat, text in patterns:
        if re.search(pat, msg, re.I) or re.search(pat, low):
            return text
    # 截断过长堆栈感信息
    clean = re.sub(r"\s+", " ", msg).strip()
    if len(clean) > 240:
        clean = clean[:240] + "…"
    return clean or "下载失败"


class JobCancelled(Exception):
    pass


def _check_cancel(job_id: str) -> None:
    job = jobs_db.get_job(job_id)
    if job and job.get("status") == "cancelled":
        raise JobCancelled("任务已取消")


async def run_download(job_id: str) -> None:
    job = jobs_db.get_job(job_id)
    if not job:
        return
    if job.get("status") == "cancelled":
        return

    media = job.get("media") or "muxed"
    if media not in MEDIA_MODES:
        media = "muxed"
    format_id = job.get("format_id") or None
    subs = bool(job.get("subs", True))
    cover = bool(job.get("cover", True))
    url = video_url(job["bvid"], int(job["page"] or 1))
    suffix = MEDIA_MODES[media]["suffix"]
    out_root = downloads_dir()
    outfile = out_root / f"{job['title']} [{job['bvid']}]" / f"p{job['page']}{suffix}.%(ext)s"
    outfile.parent.mkdir(parents=True, exist_ok=True)

    if media == "muxed" and not find_ffmpeg():
        jobs_db.update_job(
            job_id,
            status="error",
            error="未检测到 FFmpeg，无法封装音视频。请安装 FFmpeg 或把 ffmpeg.exe 放到本目录。",
        )
        notify_job_update(job_id)
        return

    loop = asyncio.get_running_loop()
    cancel_flag = {"v": False}

    def hook(d: dict) -> None:
        if cancel_flag["v"]:
            raise JobCancelled("任务已取消")
        cur = jobs_db.get_job(job_id)
        if cur and cur.get("status") == "cancelled":
            cancel_flag["v"] = True
            raise JobCancelled("任务已取消")
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            progress = round(done / total * 100, 1) if total else 0
            jobs_db.update_job(
                job_id,
                status="downloading",
                progress=progress,
                speed=d.get("_speed_str") or "",
                eta=d.get("_eta_str") or "",
            )
            notify_job_update(job_id)
        elif d.get("status") == "finished":
            jobs_db.update_job(
                job_id,
                status="muxing" if media == "muxed" else "finishing",
                progress=100,
                file=d.get("filename") or "",
            )
            notify_job_update(job_id)

    opts = download_opts_for(
        media, str(outfile), hook, format_id=format_id, subs=subs, cover=cover
    )
    jobs_db.update_job(job_id, status="downloading", progress=0, error="")
    notify_job_update(job_id)

    def _run() -> str:
        import yt_dlp

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            return resolve_download_path(info, path, media)

    try:
        _check_cancel(job_id)
        final = await loop.run_in_executor(None, _run)
        _check_cancel(job_id)
        jobs_db.update_job(
            job_id,
            status="done",
            progress=100,
            file=final,
            speed="",
            eta="",
            error="",
        )
        append_history(
            {
                "id": job_id,
                "bvid": job["bvid"],
                "title": job["title"],
                "page": job["page"],
                "media": media,
                "media_label": MEDIA_MODES[media]["label"],
                "file": os.path.basename(final),
                "path": final,
                "created": job["created"],
            }
        )
        notify_job_update(job_id)
    except JobCancelled:
        jobs_db.update_job(job_id, status="cancelled", error="任务已取消", speed="", eta="")
        notify_job_update(job_id)
    except Exception as exc:
        # 若期间被取消，保持 cancelled
        cur = jobs_db.get_job(job_id)
        if cur and cur.get("status") == "cancelled":
            notify_job_update(job_id)
            return
        jobs_db.update_job(job_id, status="error", error=friendly_error(exc), speed="", eta="")
        notify_job_update(job_id)
