"""二维码登录与 Cookie 续期。"""

from __future__ import annotations

import asyncio
import binascii
import re
import time
import urllib.parse
from typing import Any

import httpx
from fastapi import HTTPException

from bili.cards import abs_url
from bili.client import bili_headers
from bili.wbi import clear_wbi_cache
from config import BILI_REFRESH_PUBKEY, LOGIN_CHECK_INTERVAL, LOGIN_COOKIE_KEYS, PASSPORT, UA
from paths import COOKIES_PATH
from settings_store import cookie_header, settings, settings_lock, update_settings

try:
    import segno
except ImportError:
    segno = None

try:
    from Crypto.Cipher import PKCS1_OAEP
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

_refresh_task: asyncio.Task | None = None
_last_status: dict[str, Any] = {"logged_in": False}


def parse_set_cookie(resp: httpx.Response) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in resp.headers.get_list("set-cookie"):
        first = raw.split(";", 1)[0]
        if "=" in first:
            k, v = first.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def cookies_from_login_url(url: str) -> dict[str, str]:
    query = urllib.parse.urlparse(url or "").query
    out = {k: v[0] for k, v in urllib.parse.parse_qs(query, keep_blank_values=False).items() if v}
    if "SESSDATA" in out:
        out["SESSDATA"] = urllib.parse.quote(out["SESSDATA"], safe="*")
    return out


def cookie_dict() -> dict[str, str]:
    header = cookie_header()
    out: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def cookie_from_dict(jar: dict[str, str]) -> str:
    parts = [f"{k}={jar[k]}" for k in LOGIN_COOKIE_KEYS if jar.get(k)]
    for k, v in jar.items():
        if k not in LOGIN_COOKIE_KEYS and k and v:
            parts.append(f"{k}={v}")
    return "; ".join(parts)


def get_correspond_path(ts_ms: int) -> str:
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少 pycryptodome，无法计算 correspondPath")
    key = RSA.importKey(BILI_REFRESH_PUBKEY)
    cipher = PKCS1_OAEP.new(key, SHA256)
    encrypted = cipher.encrypt(f"refresh_{ts_ms}".encode())
    return binascii.b2a_hex(encrypted).decode()


async def fetch_nav_profile() -> dict:
    if not cookie_header():
        return {"logged_in": False, "status": "logged_out"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=bili_headers(),
            )
        data = resp.json().get("data") or {}
    except Exception:
        return {"logged_in": False, "status": "error", "error": "无法连接 B 站校验登录状态"}
    if not data.get("isLogin"):
        return {"logged_in": False, "status": "expired", "expired": True}
    vip = data.get("vip") or {}
    return {
        "logged_in": True,
        "status": "logged_in",
        "name": data.get("uname") or "",
        "mid": data.get("mid") or 0,
        "face": abs_url(data.get("face") or ""),
        "vip": bool(data.get("vipStatus")),
        "vip_label": (vip.get("label") or {}).get("text") or ("大会员" if data.get("vipStatus") else ""),
    }


async def cookie_info() -> dict | None:
    jar = cookie_dict()
    if not jar.get("SESSDATA"):
        return None
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                f"{PASSPORT}/cookie/info",
                params={"csrf": jar.get("bili_jct") or ""},
                headers=bili_headers(),
            )
        payload = resp.json()
    except Exception:
        return None
    if payload.get("code") == -101:
        return {"refresh": True, "expired": True, "timestamp": int(time.time() * 1000)}
    if payload.get("code") != 0:
        return None
    return payload.get("data") or {}


async def refresh_cookie() -> dict:
    """尝试用 refresh_token 刷新 SESSDATA。成功返回 status=refreshed 的 profile。"""
    s = settings()
    refresh_token = (s.get("refresh_token") or "").strip()
    jar = cookie_dict()
    if not refresh_token or not jar.get("SESSDATA"):
        return {"ok": False, "reason": "missing_token"}

    if not _HAS_CRYPTO:
        return {"ok": False, "reason": "no_crypto", "message": "缺少加密依赖，无法自动续期，请重新扫码"}

    info = await cookie_info()
    if info is None:
        return {"ok": False, "reason": "info_failed"}
    # 不需要刷新时直接返回当前状态
    if not info.get("refresh") and not info.get("expired"):
        return {"ok": True, "skipped": True}

    ts = int(info.get("timestamp") or time.time() * 1000)
    try:
        correspond = get_correspond_path(ts)
    except Exception as exc:
        return {"ok": False, "reason": "correspond", "message": str(exc)}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        corr_resp = await client.get(
            f"https://www.bilibili.com/correspond/1/{correspond}",
            headers=bili_headers(),
        )
        if corr_resp.status_code != 200:
            return {"ok": False, "reason": "correspond_http", "message": "获取 refresh_csrf 失败"}
        m = re.search(r'id="1-name"[^>]*>([^<]+)<', corr_resp.text)
        if not m:
            return {"ok": False, "reason": "refresh_csrf", "message": "页面中未找到 refresh_csrf"}
        refresh_csrf = m.group(1).strip()

        old_token = refresh_token
        refresh_resp = await client.post(
            f"{PASSPORT}/cookie/refresh",
            data={
                "csrf": jar.get("bili_jct") or "",
                "refresh_csrf": refresh_csrf,
                "source": "main_web",
                "refresh_token": old_token,
            },
            headers=bili_headers(),
        )
        payload = refresh_resp.json()
        if payload.get("code") != 0:
            return {
                "ok": False,
                "reason": "refresh_failed",
                "message": payload.get("message") or f"刷新失败 code={payload.get('code')}",
            }

        new_jar = dict(jar)
        new_jar.update(parse_set_cookie(refresh_resp))
        new_token = (payload.get("data") or {}).get("refresh_token") or old_token

        # 确认更新（用新 cookie + 旧 token）
        confirm_headers = dict(bili_headers())
        confirm_headers["Cookie"] = cookie_from_dict(new_jar)
        await client.post(
            f"{PASSPORT}/confirm/refresh",
            data={
                "csrf": new_jar.get("bili_jct") or "",
                "refresh_token": old_token,
            },
            headers=confirm_headers,
        )

    async with settings_lock():
        cur = settings()
        cur["cookie"] = cookie_from_dict(new_jar)
        cur["sessdata"] = ""
        cur["refresh_token"] = new_token
        cur["login_time"] = int(time.time())
        from settings_store import save_json
        from paths import SETTINGS_PATH

        save_json(SETTINGS_PATH, cur)

    clear_wbi_cache()
    profile = await fetch_nav_profile()
    profile["status"] = "refreshed"
    profile["refreshed"] = True
    return {"ok": True, "profile": profile}


async def ensure_login_fresh() -> dict:
    """校验登录；过期则尝试 refresh；失败则标记 expired。"""
    global _last_status
    profile = await fetch_nav_profile()
    if profile.get("logged_in"):
        # 即便已登录，也按官方 info 判断是否即将需要刷新
        info = await cookie_info()
        if info and info.get("refresh"):
            result = await refresh_cookie()
            if result.get("ok") and result.get("profile"):
                _last_status = result["profile"]
                return _last_status
        _last_status = profile
        return profile

    # 未登录 / 过期：尝试 refresh
    if cookie_header() and (settings().get("refresh_token") or "").strip():
        result = await refresh_cookie()
        if result.get("ok") and result.get("profile"):
            _last_status = result["profile"]
            return _last_status
        profile = {
            "logged_in": False,
            "status": "expired",
            "expired": True,
            "message": "登录已失效，需重新扫码",
            "refresh_error": result.get("message") or result.get("reason"),
        }
        _last_status = profile
        return profile

    if profile.get("expired"):
        profile["status"] = "expired"
        profile["message"] = "登录已失效，需重新扫码"
    _last_status = profile
    return profile


async def login_qr() -> dict:
    if segno is None:
        raise HTTPException(
            500,
            "缺少二维码依赖 segno，请双击「启动.bat」重新安装依赖，或执行 pip install segno",
        )
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            f"{PASSPORT}/qrcode/generate",
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
        )
    payload = resp.json()
    data = payload.get("data") or {}
    if payload.get("code") != 0 or not data.get("url"):
        raise HTTPException(502, payload.get("message") or "获取登录二维码失败")
    svg = segno.make(data["url"], error="m").svg_inline(scale=6, border=2, dark="#111111", light="#ffffff")
    m = re.search(r'width="(\d+)" height="(\d+)"', svg)
    if m:
        svg = svg.replace(m.group(0), f'viewBox="0 0 {m.group(1)} {m.group(2)}"', 1)
    return {"key": data["qrcode_key"], "url": data["url"], "svg": svg, "ttl": 180}


async def login_qr_poll(key: str) -> dict:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            f"{PASSPORT}/qrcode/poll",
            params={"qrcode_key": key},
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
        )
    payload = resp.json()
    data = payload.get("data") or {}
    code = data.get("code")
    if payload.get("code") != 0:
        raise HTTPException(502, payload.get("message") or "轮询登录状态失败")
    if code == 86101:
        return {"status": "waiting", "message": "等待扫码"}
    if code == 86090:
        return {"status": "scanned", "message": "已扫码，请在手机上点击确认"}
    if code == 86038:
        return {"status": "expired", "message": "二维码已过期，请重新获取"}
    if code != 0:
        return {"status": "error", "message": data.get("message") or f"未知状态 {code}"}

    jar = cookies_from_login_url(data.get("url") or "")
    jar.update(parse_set_cookie(resp))
    if not jar.get("SESSDATA"):
        raise HTTPException(502, "登录成功但没有拿到 SESSDATA，请重试")
    parts = [f"{k}={jar[k]}" for k in LOGIN_COOKIE_KEYS if jar.get(k)]

    async def mutator(s: dict) -> None:
        s["cookie"] = "; ".join(parts)
        s["sessdata"] = ""
        s["refresh_token"] = data.get("refresh_token") or ""
        s["login_via"] = "qrcode"
        s["login_time"] = int(time.time())

    await update_settings(mutator)
    clear_wbi_cache()
    profile = await fetch_nav_profile()
    return {"status": "done", "message": "登录成功", "profile": profile}


async def login_logout() -> dict:
    async def mutator(s: dict) -> None:
        for k in ("cookie", "sessdata", "refresh_token", "login_via", "login_time"):
            s.pop(k, None)

    await update_settings(mutator)
    if COOKIES_PATH.exists():
        COOKIES_PATH.unlink()
    clear_wbi_cache()
    return {"ok": True}


async def _periodic_check() -> None:
    while True:
        try:
            await ensure_login_fresh()
        except Exception:
            pass
        await asyncio.sleep(LOGIN_CHECK_INTERVAL)


async def start_login_watcher() -> None:
    global _refresh_task
    try:
        await ensure_login_fresh()
    except Exception:
        pass
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_periodic_check())


async def stop_login_watcher() -> None:
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
        try:
            await _refresh_task
        except (asyncio.CancelledError, Exception):
            pass
    _refresh_task = None
