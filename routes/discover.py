"""热门、搜索、UP 空间、链接解析。"""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException, Query

from bili.cards import abs_url, card_from_popular, card_from_search, fmt_count, fmt_duration, strip_em
from bili.client import get_json
from media.ytdlp_util import ydl_base
import yt_dlp

router = APIRouter()


def list_space_bvids(mid: int, pn: int, ps: int) -> tuple[list[str], int]:
    start = (pn - 1) * ps + 1
    end = pn * ps
    opts = ydl_base()
    opts.update({"extract_flat": True, "playliststart": start, "playlistend": end})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://space.bilibili.com/{mid}/video", download=False)
    bvids = [e.get("id") for e in (info.get("entries") or []) if e and str(e.get("id", "")).startswith("BV")]
    total = info.get("playlist_count") or info.get("n_entries") or 0
    return bvids, int(total or 0)


# avoid circular — define locally (ydlp util doesn't have list_space)
async def enrich_bvids(bvids: list[str], author: str, mid: int) -> list[dict]:
    items = []
    for bvid in bvids:
        try:
            payload = await get_json(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                raise_biz=False,
            )
        except Exception:
            items.append(
                {
                    "bvid": bvid,
                    "title": bvid,
                    "author": author,
                    "mid": mid,
                    "pic": "",
                    "play": "",
                    "danmaku": "",
                    "duration": "",
                    "desc": "",
                    "pubdate": 0,
                }
            )
            continue
        data = payload.get("data") or {}
        if payload.get("code") != 0 or not data:
            items.append(
                {
                    "bvid": bvid,
                    "title": bvid,
                    "author": author,
                    "mid": mid,
                    "pic": "",
                    "play": "",
                    "danmaku": "",
                    "duration": "",
                    "desc": "",
                    "pubdate": 0,
                }
            )
            continue
        stat = data.get("stat") or {}
        items.append(
            {
                "bvid": data.get("bvid") or bvid,
                "title": data.get("title") or bvid,
                "author": author,
                "mid": mid,
                "pic": abs_url(data.get("pic") or ""),
                "play": fmt_count(stat.get("view")),
                "danmaku": fmt_count(stat.get("danmaku")),
                "duration": fmt_duration(data.get("duration")),
                "desc": data.get("desc") or "",
                "pubdate": data.get("pubdate") or 0,
            }
        )
    return items


async def search_up_videos(name: str, mid: int, pn: int, ps: int) -> tuple[list[dict], str]:
    if not name:
        return [], "search"
    payload = await get_json(
        "https://api.bilibili.com/x/web-interface/wbi/search/type",
        params={"search_type": "video", "keyword": name, "page": pn, "page_size": 20, "order": "pubdate"},
        wbi=True,
        raise_biz=False,
    )
    result = ((payload.get("data") or {}).get("result") or [])
    items = [card_from_search(x) for x in result if x.get("mid") == mid]
    return items[:ps], "search"


@router.get("/api/popular")
async def popular(pn: int = 1, ps: int = 20) -> dict:
    payload = await get_json(
        "https://api.bilibili.com/x/web-interface/popular",
        params={"pn": pn, "ps": ps},
    )
    items = [card_from_popular(x) for x in (payload.get("data", {}).get("list") or [])]
    return {"items": items, "page": pn}


@router.get("/api/search")
async def search(q: str = Query(min_length=1), kind: str = "video", page: int = 1) -> dict:
    search_type = "bili_user" if kind == "up" else "video"
    payload = await get_json(
        "https://api.bilibili.com/x/web-interface/wbi/search/type",
        params={"search_type": search_type, "keyword": q, "page": page, "page_size": 20},
        wbi=True,
    )
    result = (payload.get("data") or {}).get("result") or []
    if kind == "up":
        users = []
        for item in result:
            users.append(
                {
                    "mid": item.get("mid"),
                    "name": strip_em(item.get("uname") or ""),
                    "sign": item.get("usign") or "",
                    "face": abs_url(item.get("upic") or ""),
                    "fans": fmt_count(item.get("fans")),
                    "videos": item.get("videos") or 0,
                    "level": item.get("level") or 0,
                }
            )
        return {"kind": "up", "items": users, "page": page}
    return {"kind": "video", "items": [card_from_search(x) for x in result], "page": page}


@router.get("/api/up/{mid}")
async def up_space(mid: int, pn: int = 1, ps: int = 12) -> dict:
    card_payload = await get_json(
        "https://api.bilibili.com/x/web-interface/card",
        params={"mid": mid},
        raise_biz=False,
    )
    card = ((card_payload.get("data") or {}).get("card") or {})
    profile = {
        "mid": mid,
        "name": card.get("name") or "",
        "sign": card.get("sign") or "",
        "face": abs_url(card.get("face") or ""),
        "fans": fmt_count(card.get("fans")),
        "attention": fmt_count(card.get("attention")),
    }
    note = ""
    total = 0
    try:
        bvids, total = await asyncio.to_thread(list_space_bvids, mid, pn, ps)
        items = await enrich_bvids(bvids, profile["name"], mid)
        source = "space"
    except Exception:
        items, source = await search_up_videos(profile["name"], mid, pn, ps)
        note = "空间接口被风控，当前展示该 UP 的检索结果。配置 Cookie 后可再试完整空间。"
        total = 0
    return {"profile": profile, "items": items, "page": pn, "count": total, "source": source, "note": note}


@router.get("/api/resolve")
async def resolve(q: str) -> dict:
    text = q.strip()
    match = re.search(r"BV[0-9A-Za-z]+", text)
    if match:
        return {"bvid": match.group(0)}
    av = re.search(r"av(\d+)", text, re.I)
    if not av and text.isdigit():
        av_id = text
    else:
        av_id = av.group(1) if av else ""
    if av_id:
        payload = await get_json(
            "https://api.bilibili.com/x/web-interface/view",
            params={"aid": av_id},
            raise_biz=False,
        )
        if payload.get("code") == 0:
            return {"bvid": payload["data"]["bvid"]}
    raise HTTPException(400, "无法识别链接或 BV / AV 号")
