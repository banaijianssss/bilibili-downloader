"""视频详情与播放地址。"""

from __future__ import annotations

import asyncio
import re
import time
import urllib.parse

from fastapi import APIRouter, HTTPException

from bili.cards import abs_url, fmt_count, fmt_duration
from bili.client import get_json
from media.ytdlp_util import (
    extract,
    pick_streams,
    stream_label,
    summarize_formats,
    video_url,
)
from settings_store import cookie_header

router = APIRouter()

_info_cache: dict[str, tuple[float, dict]] = {}


def get_info_cache() -> dict:
    return _info_cache


@router.get("/api/video/{bvid}")
async def video_detail(bvid: str, page: int = 1) -> dict:
    bvid = bvid.strip()
    if not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
        raise HTTPException(400, "无效的 BV 号")
    cache_key = f"{bvid}:{page}:{bool(cookie_header())}"
    cached = _info_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]

    view = await get_json(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
    )
    data = view["data"]
    pages = [
        {
            "page": p.get("page"),
            "cid": p.get("cid"),
            "part": p.get("part"),
            "duration": fmt_duration(p.get("duration")),
        }
        for p in (data.get("pages") or [])
    ]
    url = video_url(bvid, page)
    try:
        info = await asyncio.to_thread(extract, url)
    except Exception as exc:
        raise HTTPException(502, f"解析失败：{exc}") from exc
    formats = summarize_formats(info)
    play = pick_streams(formats, prefer_browser=True)
    best = pick_streams(formats, prefer_browser=False)
    owner = data.get("owner") or {}
    payload = {
        "bvid": bvid,
        "title": data.get("title") or info.get("title") or "",
        "desc": data.get("desc") or "",
        "pic": abs_url(data.get("pic") or info.get("thumbnail") or ""),
        "author": owner.get("name") or info.get("uploader") or "",
        "mid": owner.get("mid") or 0,
        "duration": fmt_duration(data.get("duration")),
        "play": fmt_count((data.get("stat") or {}).get("view")),
        "pages": pages,
        "page": page,
        "formats": [{k: v for k, v in f.items() if k != "url"} for f in formats],
        "play_stream": {
            "video_id": play["video"]["format_id"] if play["video"] else None,
            "audio_id": play["audio"]["format_id"] if play["audio"] else None,
            "label": stream_label(play["video"]),
        },
        "best_stream": {
            "video_id": best["video"]["format_id"] if best["video"] else None,
            "audio_id": best["audio"]["format_id"] if best["audio"] else None,
            "label": stream_label(best["video"]),
        },
        "cookie": bool(cookie_header()),
    }
    _info_cache[cache_key] = (time.time() + 600, payload)
    _info_cache[cache_key + ":raw"] = (time.time() + 600, {"formats": formats})
    return payload


def raw_formats(bvid: str, page: int) -> list[dict]:
    cache_key = f"{bvid}:{page}:{bool(cookie_header())}:raw"
    cached = _info_cache.get(cache_key)
    if not cached or cached[0] < time.time():
        raise HTTPException(409, "请先打开视频以完成解析")
    return cached[1]["formats"]


@router.get("/api/play/{bvid}")
async def play_urls(bvid: str, page: int = 1, mode: str = "compat") -> dict:
    formats = raw_formats(bvid, page)
    picked = pick_streams(formats, prefer_browser=(mode != "best"))
    video = picked["video"]
    audio = picked["audio"]
    if not video:
        raise HTTPException(404, "没有可播放的视频流")

    def token(url: str) -> str:
        return "/api/media?u=" + urllib.parse.quote(url, safe="")

    return {
        "mode": "compat" if mode != "best" else "best",
        "label": stream_label(video),
        "video": token(video["url"]),
        "audio": token(audio["url"]) if audio else None,
        "codec": video.get("codec"),
        "height": video.get("height"),
        "fps": video.get("fps"),
        "browser_ok": video.get("browser_ok"),
    }
