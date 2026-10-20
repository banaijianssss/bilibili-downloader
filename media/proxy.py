"""图片 / 媒体代理。"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from config import UA
from media.ytdlp_util import host_allowed

router = APIRouter()


@router.get("/api/img")
async def img_proxy(u: str) -> Response:
    if not u.startswith("https://") or not host_allowed(u):
        raise HTTPException(400, "不允许的图片地址")
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            upstream = await client.get(u, headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    except Exception:
        raise HTTPException(502, "图片拉取失败")
    if upstream.status_code != 200:
        raise HTTPException(upstream.status_code, "图片拉取失败")
    return Response(
        upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/media")
async def media_proxy(u: str, request: Request) -> StreamingResponse:
    if not host_allowed(u):
        raise HTTPException(400, "不允许的媒体地址")
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    client = httpx.AsyncClient(timeout=None, follow_redirects=True)
    try:
        upstream = await client.send(client.build_request("GET", u, headers=headers), stream=True)
    except Exception:
        await client.aclose()
        raise HTTPException(502, "媒体拉取失败")
    passthrough = {}
    for key in ("content-type", "content-length", "content-range", "accept-ranges"):
        if key in upstream.headers:
            passthrough[key] = upstream.headers[key]
    passthrough.setdefault("accept-ranges", "bytes")

    async def body():
        try:
            async for chunk in upstream.aiter_bytes(64 * 1024):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=passthrough)
