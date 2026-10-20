"""搜索 / 热门 / 空间卡片规范化。"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any


def strip_em(text: str) -> str:
    return re.sub(r"</?em[^>]*>", "", text or "")


def abs_url(url: str) -> str:
    """补全协议；B 站图片有防盗链，统一改走本地 /api/img 代理。"""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    host = urllib.parse.urlparse(url).hostname or ""
    if host.endswith("hdslb.com") or host.endswith("bilibili.com"):
        return "/api/img?u=" + urllib.parse.quote(url, safe="")
    return url


def fmt_duration(value: Any) -> str:
    if isinstance(value, str) and ":" in value:
        return value
    try:
        sec = int(value or 0)
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_count(n: Any) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "0"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def card_from_search(item: dict) -> dict:
    return {
        "bvid": item.get("bvid") or "",
        "title": strip_em(item.get("title") or ""),
        "author": item.get("author") or "",
        "mid": item.get("mid") or 0,
        "pic": abs_url(item.get("pic") or ""),
        "play": fmt_count(item.get("play")),
        "danmaku": fmt_count(item.get("video_review") or item.get("danmaku")),
        "duration": fmt_duration(item.get("duration")),
        "desc": strip_em(item.get("description") or ""),
        "pubdate": item.get("pubdate") or 0,
    }


def card_from_popular(item: dict) -> dict:
    owner = item.get("owner") or {}
    stat = item.get("stat") or {}
    return {
        "bvid": item.get("bvid") or "",
        "title": item.get("title") or "",
        "author": owner.get("name") or "",
        "mid": owner.get("mid") or 0,
        "pic": abs_url(item.get("pic") or ""),
        "play": fmt_count(stat.get("view")),
        "danmaku": fmt_count(stat.get("danmaku")),
        "duration": fmt_duration(item.get("duration")),
        "desc": item.get("desc") or "",
        "pubdate": item.get("pubdate") or 0,
    }


def card_from_space(item: dict) -> dict:
    return {
        "bvid": item.get("bvid") or "",
        "title": item.get("title") or "",
        "author": item.get("author") or "",
        "mid": item.get("mid") or 0,
        "pic": abs_url(item.get("pic") or ""),
        "play": fmt_count(item.get("play")),
        "danmaku": fmt_count(item.get("video_review")),
        "duration": fmt_duration(item.get("length") or item.get("duration")),
        "desc": item.get("description") or "",
        "pubdate": item.get("created") or 0,
    }
