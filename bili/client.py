"""统一 B 站 HTTP 客户端：WBI、限速、退避重试、错误码映射。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import HTTPException

from bili.wbi import clear_wbi_cache, get_cached_mixin, mixin_key, set_cached_mixin, sign_wbi
from config import API_MIN_INTERVAL, UA
from settings_store import cookie_header

ERROR_MESSAGES = {
    -101: "账号未登录或 Cookie 已失效，请重新扫码",
    -111: "csrf 校验失败，请重新登录",
    -352: "风控校验失败（-352），请稍后再试或重新登录",
    -400: "请求参数错误",
    -403: "访问被拒绝",
    -404: "资源不存在",
    -412: "请求被拦截（412），请稍后重试或配置 Cookie",
    -509: "请求过于频繁，请稍后再试",
    -799: "请求过于频繁",
    62002: "稿件不可见",
    62004: "稿件审核中",
    87012: "该视频需大会员",
}


class RateLimiter:
    def __init__(self, min_interval: float = API_MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


_limiter = RateLimiter()
_client: httpx.AsyncClient | None = None


def bili_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    ck = cookie_header()
    if ck:
        h["Cookie"] = ck
    if extra:
        h.update(extra)
    return h


def map_error(code: int | None, message: str | None = None) -> str:
    if code is None:
        return message or "未知错误"
    mapped = ERROR_MESSAGES.get(int(code))
    if mapped:
        return mapped
    return message or f"接口错误 {code}"


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=20, follow_redirects=True)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def request(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
    wbi: bool = False,
    max_retries: int = 3,
    raise_biz: bool = True,
) -> dict[str, Any]:
    """发起 B 站 API 请求，带限速与指数退避。返回 JSON dict。"""
    client = await get_client()
    hdrs = bili_headers(headers)
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        await _limiter.acquire()
        req_params = dict(params or {})
        try:
            if wbi:
                mixin = await ensure_wbi(client)
                req_params = sign_wbi(req_params, mixin)
            resp = await client.request(method, url, params=req_params, data=data, headers=hdrs)
            # 硬风控 / 网关错误
            if resp.status_code in (412, 429, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            payload = resp.json()
            code = payload.get("code")
            if raise_biz and code not in (0, None):
                # -352 等业务风控可重试
                if int(code) in (-352, -412, -509, -799) and attempt < max_retries - 1:
                    await asyncio.sleep(0.8 * (2**attempt))
                    clear_wbi_cache()
                    continue
                raise HTTPException(502, map_error(code, payload.get("message")))
            return payload
        except HTTPException:
            raise
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(0.6 * (2**attempt))
                continue
            break

    detail = "网络请求失败"
    if last_exc:
        detail = f"网络请求失败：{last_exc}"
    raise HTTPException(502, detail)


async def ensure_wbi(client: httpx.AsyncClient | None = None) -> str:
    cached = get_cached_mixin()
    if cached:
        return cached
    client = client or await get_client()
    await _limiter.acquire()
    resp = await client.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=bili_headers(),
    )
    resp.raise_for_status()
    payload = resp.json()
    img = payload.get("data", {}).get("wbi_img", {})
    img_key = img.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = img.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    if not img_key or not sub_key:
        raise HTTPException(502, "无法获取哔哩 WBI 签名密钥")
    key = mixin_key(img_key, sub_key)
    set_cached_mixin(key)
    return key


async def get_json(url: str, **kwargs) -> dict:
    return await request("GET", url, **kwargs)


async def post_form(url: str, data: dict, **kwargs) -> dict:
    return await request("POST", url, data=data, **kwargs)
