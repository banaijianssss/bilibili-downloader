"""健康检查与设置。"""

from __future__ import annotations

import sys

import yt_dlp
from fastapi import APIRouter

from bili.wbi import clear_wbi_cache
from media.ytdlp_util import downloads_dir, find_ffmpeg
from settings_store import cookie_header, settings, settings_lock, save_json
from paths import SETTINGS_PATH

router = APIRouter()

# 视频 info 缓存清理由 video 路由维护；这里只清 wbi
_info_cache_ref: dict | None = None


def bind_info_cache(cache: dict) -> None:
    global _info_cache_ref
    _info_cache_ref = cache


@router.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "engine": f"yt-dlp {yt_dlp.version.__version__}",
        "platform": sys.platform,
        "ffmpeg": find_ffmpeg() or "",
        "cookie": bool(cookie_header()),
        "downloads": str(downloads_dir()),
    }


@router.get("/api/settings")
async def get_settings() -> dict:
    s = settings()
    return {
        "has_cookie": bool(cookie_header()),
        "sessdata_set": bool(s.get("sessdata") or s.get("cookie")),
        "downloads": str(downloads_dir()),
    }


@router.post("/api/settings")
async def put_settings(body: dict) -> dict:
    async with settings_lock():
        s = settings()
        if "sessdata" in body:
            s["sessdata"] = str(body.get("sessdata") or "").strip()
        if "cookie" in body:
            s["cookie"] = str(body.get("cookie") or "").strip()
        if "outdir" in body or "downloads" in body:
            out = str(body.get("outdir") or body.get("downloads") or "").strip()
            if out:
                s["outdir"] = out
            else:
                s.pop("outdir", None)
                s.pop("downloads", None)
        save_json(SETTINGS_PATH, s)
    if _info_cache_ref is not None:
        _info_cache_ref.clear()
    clear_wbi_cache()
    return {"ok": True, "has_cookie": bool(cookie_header())}
