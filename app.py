"""bilibili下载器 — Windows 本地检索、高画质播放与存档。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

try:
    import segno
except ImportError:  # 缺少依赖时二维码接口会给出明确提示
    segno = None

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
SETTINGS_PATH = DATA / "settings.json"
HISTORY_PATH = DATA / "history.json"



UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]
CDN_SUFFIXES = (
    "bilivideo.com",
    "bilivideo.cn",
    "hdslb.com",
    "bilibili.com",
    "akamaized.net",
    "bstarstatic.com",
)
QN_LABEL = {
    6: "240P",
    16: "360P",
    32: "480P",
    64: "720P",
    74: "720P60",
    80: "1080P",
    100: "智能修复",
    112: "1080P+",
    116: "1080P60",
    120: "4K",
    125: "HDR",
    126: "杜比视界",
    127: "8K",
}

# 下载介质：muxed=音视频封装，video=纯视频轨，audio=纯音频轨
MEDIA_MODES = {
    "muxed": {
        "label": "音视频",
        "format": "bv*+ba/b",
        "merge": "mp4",
        "suffix": "",
    },
    "video": {
        "label": "纯视频",
        "format": "bv*/b",
        "merge": None,
        "suffix": ".video",
    },
    "audio": {
        "label": "纯音频",
        "format": "ba/b",
        "merge": None,
        "suffix": ".audio",
    },
}

PASSPORT = "https://passport.bilibili.com/x/passport-login/web"
LOGIN_COOKIE_KEYS = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")

app = FastAPI(title="bilibili下载器", version="1.2.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_cache(request: Request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp

_wbi_cache: dict[str, Any] = {"key": "", "exp": 0.0}
_info_cache: dict[str, tuple[float, dict]] = {}
_jobs: dict[str, dict] = {}
_jobs_lock = asyncio.Lock()
_settings_lock = asyncio.Lock()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def default_user_downloads() -> Path:
    """Windows/macOS/Linux user Downloads folder."""
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / "Downloads"


def downloads_dir() -> Path:
    """Prefer settings.outdir override; else this PC's Downloads folder."""
    s = load_json(SETTINGS_PATH, {})
    custom = str(s.get("outdir") or s.get("downloads") or "").strip()
    if custom:
        p = Path(custom)
        p.mkdir(parents=True, exist_ok=True)
        return p
    p = default_user_downloads()
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        fallback = ROOT / "downloads"
        fallback.mkdir(exist_ok=True)
        return fallback


DOWNLOADS = downloads_dir()


def settings() -> dict:
    data = load_json(SETTINGS_PATH, {})
    data.setdefault("sessdata", "")
    data.setdefault("cookie", "")
    return data


def cookie_header() -> str:
    s = settings()
    raw = (s.get("cookie") or "").strip()
    if raw:
        return raw
    sess = (s.get("sessdata") or "").strip()
    if sess:
        return f"SESSDATA={sess}"
    return ""


def cookiefile() -> str | None:
    header = cookie_header()
    if not header:
        return None
    path = DATA / "cookies.txt"
    lines = ["# Netscape HTTP Cookie File"]
    for part in header.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{name.strip()}\t{value.strip()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def bili_headers() -> dict[str, str]:
    h = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    ck = cookie_header()
    if ck:
        h["Cookie"] = ck
    return h


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def sign_wbi(params: dict, mixin: str) -> dict:
    signed = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
    signed["wts"] = int(time.time())
    signed = dict(sorted(signed.items()))
    query = urllib.parse.urlencode(signed)
    signed["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return signed


async def wbi_mixin(client: httpx.AsyncClient) -> str:
    now = time.time()
    if _wbi_cache["key"] and _wbi_cache["exp"] > now:
        return _wbi_cache["key"]
    resp = await client.get("https://api.bilibili.com/x/web-interface/nav", headers=bili_headers())
    resp.raise_for_status()
    payload = resp.json()
    img = payload.get("data", {}).get("wbi_img", {})
    img_key = img.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = img.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    if not img_key or not sub_key:
        raise HTTPException(502, "无法获取哔哩 WBI 签名密钥")
    key = mixin_key(img_key, sub_key)
    _wbi_cache["key"] = key
    _wbi_cache["exp"] = now + 1800
    return key


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


def safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', " ", text or "")
    text = re.sub(r"[\x00-\x1f]", "", text)
    text = text.strip(" .")
    text = re.sub(r"\s+", " ", text)
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    if text.upper() in reserved:
        text = f"_{text}"
    return text[:80] or "video"


def find_ffmpeg() -> str | None:
    names = ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        ROOT / "ffmpeg.exe",
        ROOT / "ffmpeg" / "ffmpeg.exe",
        ROOT / "bin" / "ffmpeg.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def codec_family(vcodec: str) -> str:
    v = (vcodec or "").lower()
    if v.startswith("avc") or v in {"h264", "avc1"}:
        return "H.264"
    if "hev" in v or v.startswith("hvc") or "h265" in v:
        return "HEVC"
    if v.startswith("av01") or "av1" in v:
        return "AV1"
    if v.startswith("vp9"):
        return "VP9"
    return vcodec or "unknown"


def playable_in_browser(vcodec: str, acodec: str) -> bool:
    v = (vcodec or "").lower()
    a = (acodec or "").lower()
    video_ok = v.startswith("avc") or v in {"h264", "none"}
    audio_ok = a in {"none", ""} or a.startswith("mp4a") or "aac" in a
    return video_ok and audio_ok


def summarize_formats(info: dict) -> list[dict]:
    rows = []
    for f in info.get("formats") or []:
        height = f.get("height") or 0
        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        if vcodec == "none" and acodec == "none":
            continue
        rows.append(
            {
                "format_id": f.get("format_id"),
                "height": height,
                "width": f.get("width") or 0,
                "fps": f.get("fps") or 0,
                "vcodec": vcodec,
                "acodec": acodec,
                "codec": codec_family(vcodec) if vcodec != "none" else "音频",
                "tbr": round(f.get("tbr") or 0),
                "ext": f.get("ext") or "",
                "filesize": f.get("filesize") or f.get("filesize_approx") or 0,
                "note": f.get("format_note") or "",
                "has_video": vcodec != "none",
                "has_audio": acodec != "none",
                "browser_ok": playable_in_browser(vcodec, acodec) and vcodec != "none",
                "url": f.get("url") or "",
            }
        )
    rows.sort(key=lambda r: (r["height"], r["fps"], r["tbr"]), reverse=True)
    return rows


def pick_streams(formats: list[dict], prefer_browser: bool) -> dict:
    videos = [f for f in formats if f["has_video"] and f["url"]]
    audios = [f for f in formats if f["has_audio"] and not f["has_video"] and f["url"]]
    if prefer_browser:
        browser_videos = [f for f in videos if f["browser_ok"]]
        if browser_videos:
            videos = browser_videos
    video = videos[0] if videos else None
    audio = audios[0] if audios else None
    if video and video["has_audio"]:
        audio = None
    return {"video": video, "audio": audio}


def ydl_base() -> dict:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 20,
        "retries": 3,
        "windowsfilenames": True,
        "extractor_args": {"bilibili": {"prefer_multi_flv": [""]}},
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    cf = cookiefile()
    if cf:
        opts["cookiefile"] = cf
    return opts


def extract(url: str) -> dict:
    opts = ydl_base()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def video_url(bvid: str, page: int) -> str:
    url = f"https://www.bilibili.com/video/{bvid}"
    if page and page > 1:
        url += f"?p={page}"
    return url


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "engine": f"yt-dlp {yt_dlp.version.__version__}",
        "platform": sys.platform,
        "ffmpeg": find_ffmpeg() or "",
        "cookie": bool(cookie_header()),
        "downloads": str(downloads_dir()),
    }


@app.get("/api/settings")
async def get_settings() -> dict:
    s = settings()
    return {
        "has_cookie": bool(cookie_header()),
        "sessdata_set": bool(s.get("sessdata") or s.get("cookie")),
        "downloads": str(downloads_dir()),
    }


@app.post("/api/settings")
async def put_settings(body: dict) -> dict:
    async with _settings_lock:
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
    _info_cache.clear()
    _wbi_cache["exp"] = 0
    return {"ok": True, "has_cookie": bool(cookie_header())}


def parse_set_cookie(resp: httpx.Response) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in resp.headers.get_list("set-cookie"):
        first = raw.split(";", 1)[0]
        if "=" in first:
            k, v = first.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def cookies_from_login_url(url: str) -> dict[str, str]:
    """扫码成功后 data.url 的查询串里也带有登录 Cookie，用作兜底。"""
    query = urllib.parse.urlparse(url or "").query
    out = {k: v[0] for k, v in urllib.parse.parse_qs(query, keep_blank_values=False).items() if v}
    if "SESSDATA" in out:  # parse_qs 会解码，Cookie 里需要保持浏览器里的编码形式
        out["SESSDATA"] = urllib.parse.quote(out["SESSDATA"], safe="*")
    return out


async def login_profile() -> dict:
    """用当前 Cookie 询问 B 站账号状态。"""
    if not cookie_header():
        return {"logged_in": False}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get("https://api.bilibili.com/x/web-interface/nav", headers=bili_headers())
        data = (resp.json().get("data") or {})
    except Exception:
        return {"logged_in": False, "error": "无法连接 B 站校验登录状态"}
    if not data.get("isLogin"):
        return {"logged_in": False, "expired": True}
    vip = data.get("vip") or {}
    return {
        "logged_in": True,
        "name": data.get("uname") or "",
        "mid": data.get("mid") or 0,
        "face": abs_url(data.get("face") or ""),
        "vip": bool(data.get("vipStatus")),
        "vip_label": (vip.get("label") or {}).get("text") or ("大会员" if data.get("vipStatus") else ""),
    }


@app.get("/api/login/qr")
async def login_qr() -> dict:
    if segno is None:
        raise HTTPException(500, "缺少二维码依赖 segno，请双击「启动.bat」重新安装依赖，或执行 pip install segno")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(f"{PASSPORT}/qrcode/generate", headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    payload = resp.json()
    data = payload.get("data") or {}
    if payload.get("code") != 0 or not data.get("url"):
        raise HTTPException(502, payload.get("message") or "获取登录二维码失败")
    svg = segno.make(data["url"], error="m").svg_inline(scale=6, border=2, dark="#111111", light="#ffffff")
    m = re.search(r'width="(\d+)" height="(\d+)"', svg)
    if m:  # 去掉固定尺寸并补 viewBox，让 CSS 能缩放二维码
        svg = svg.replace(m.group(0), f'viewBox="0 0 {m.group(1)} {m.group(2)}"', 1)
    return {"key": data["qrcode_key"], "url": data["url"], "svg": svg, "ttl": 180}


@app.get("/api/login/qr/poll")
async def login_qr_poll(key: str = Query(min_length=8, max_length=64)) -> dict:
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
    jar.update(parse_set_cookie(resp))  # 响应头里的值优先
    if not jar.get("SESSDATA"):
        raise HTTPException(502, "登录成功但没有拿到 SESSDATA，请重试")
    parts = [f"{k}={jar[k]}" for k in LOGIN_COOKIE_KEYS if jar.get(k)]
    async with _settings_lock:
        s = settings()
        s["cookie"] = "; ".join(parts)
        s["sessdata"] = ""
        s["refresh_token"] = data.get("refresh_token") or ""
        s["login_via"] = "qrcode"
        s["login_time"] = int(time.time())
        save_json(SETTINGS_PATH, s)
    _info_cache.clear()
    _wbi_cache["exp"] = 0
    profile = await login_profile()
    return {"status": "done", "message": "登录成功", "profile": profile}


@app.get("/api/login/status")
async def login_status() -> dict:
    return await login_profile()


@app.post("/api/login/logout")
async def login_logout() -> dict:
    async with _settings_lock:
        s = settings()
        for k in ("cookie", "sessdata", "refresh_token", "login_via", "login_time"):
            s.pop(k, None)
        save_json(SETTINGS_PATH, s)
    cf = DATA / "cookies.txt"
    if cf.exists():
        cf.unlink()
    _info_cache.clear()
    _wbi_cache["exp"] = 0
    return {"ok": True}


@app.get("/api/popular")
async def popular(pn: int = 1, ps: int = 20) -> dict:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params={"pn": pn, "ps": ps},
            headers=bili_headers(),
        )
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("code") != 0:
        raise HTTPException(502, payload.get("message") or "热门接口失败")
    items = [card_from_popular(x) for x in (payload.get("data", {}).get("list") or [])]
    return {"items": items, "page": pn}


@app.get("/api/search")
async def search(q: str = Query(min_length=1), kind: str = "video", page: int = 1) -> dict:
    search_type = "bili_user" if kind == "up" else "video"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        mixin = await wbi_mixin(client)
        params = sign_wbi(
            {"search_type": search_type, "keyword": q, "page": page, "page_size": 20},
            mixin,
        )
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/wbi/search/type",
            params=params,
            headers=bili_headers(),
        )
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("code") != 0:
        raise HTTPException(502, payload.get("message") or "搜索失败")
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


async def enrich_bvids(bvids: list[str], author: str, mid: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        responses = await asyncio.gather(
            *[
                client.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params={"bvid": bvid},
                    headers=bili_headers(),
                )
                for bvid in bvids
            ],
            return_exceptions=True,
        )
    items = []
    for bvid, resp in zip(bvids, responses):
        if isinstance(resp, Exception):
            items.append({"bvid": bvid, "title": bvid, "author": author, "mid": mid, "pic": "", "play": "", "danmaku": "", "duration": "", "desc": "", "pubdate": 0})
            continue
        payload = resp.json()
        data = payload.get("data") or {}
        if payload.get("code") != 0 or not data:
            items.append({"bvid": bvid, "title": bvid, "author": author, "mid": mid, "pic": "", "play": "", "danmaku": "", "duration": "", "desc": "", "pubdate": 0})
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
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        mixin = await wbi_mixin(client)
        params = sign_wbi(
            {"search_type": "video", "keyword": name, "page": pn, "page_size": 20, "order": "pubdate"},
            mixin,
        )
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/wbi/search/type",
            params=params,
            headers=bili_headers(),
        )
    result = ((resp.json().get("data") or {}).get("result") or [])
    items = [card_from_search(x) for x in result if x.get("mid") == mid]
    return items[:ps], "search"


@app.get("/api/up/{mid}")
async def up_space(mid: int, pn: int = 1, ps: int = 12) -> dict:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        card_resp = await client.get(
            "https://api.bilibili.com/x/web-interface/card",
            params={"mid": mid},
            headers=bili_headers(),
        )
    card = ((card_resp.json().get("data") or {}).get("card") or {})
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
        # Space endpoints often return 412 outside a browser session. Search still works.
        items, source = await search_up_videos(profile["name"], mid, pn, ps)
        note = "空间接口被风控，当前展示该 UP 的检索结果。配置 Cookie 后可再试完整空间。"
        total = 0
    return {"profile": profile, "items": items, "page": pn, "count": total, "source": source, "note": note}


@app.get("/api/video/{bvid}")
async def video_detail(bvid: str, page: int = 1) -> dict:
    bvid = bvid.strip()
    if not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
        raise HTTPException(400, "无效的 BV 号")
    cache_key = f"{bvid}:{page}:{bool(cookie_header())}"
    cached = _info_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        view_resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers=bili_headers(),
        )
    view = view_resp.json()
    if view.get("code") != 0:
        raise HTTPException(502, view.get("message") or "稿件信息获取失败")
    data = view["data"]
    pages = [
        {"page": p.get("page"), "cid": p.get("cid"), "part": p.get("part"), "duration": fmt_duration(p.get("duration"))}
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
    # keep raw urls in a side cache for the proxy picker
    _info_cache[cache_key + ":raw"] = (time.time() + 600, {"formats": formats})
    return payload


def stream_label(video: dict | None) -> str:
    if not video:
        return "无可用流"
    fps = f"{int(video['fps'])}帧" if video.get("fps") else ""
    height = f"{video['height']}P" if video.get("height") else video.get("note") or "未知"
    return " ".join(x for x in (height, fps, video.get("codec")) if x)


def raw_formats(bvid: str, page: int) -> list[dict]:
    cache_key = f"{bvid}:{page}:{bool(cookie_header())}:raw"
    cached = _info_cache.get(cache_key)
    if not cached or cached[0] < time.time():
        raise HTTPException(409, "请先打开视频以完成解析")
    return cached[1]["formats"]


@app.get("/api/play/{bvid}")
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


def host_allowed(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return any(host == s or host.endswith("." + s) for s in CDN_SUFFIXES)


@app.get("/api/img")
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


@app.get("/api/media")
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


@app.get("/api/resolve")
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
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"aid": av_id},
                headers=bili_headers(),
            )
        payload = resp.json()
        if payload.get("code") == 0:
            return {"bvid": payload["data"]["bvid"]}
    raise HTTPException(400, "无法识别链接或 BV / AV 号")



def normalize_media(raw: str | None) -> str:
    """Accept UI aliases; default to muxed 音视频."""
    key = (raw or "muxed").strip().lower()
    aliases = {
        "muxed": "muxed",
        "full": "muxed",
        "av": "muxed",
        "both": "muxed",
        "音视频": "muxed",
        "video": "video",
        "v": "video",
        "纯视频": "video",
        "audio": "audio",
        "a": "audio",
        "纯音频": "audio",
    }
    mode = aliases.get(key, key)
    if mode not in MEDIA_MODES:
        raise HTTPException(400, "无效的下载类型，可选 muxed / video / audio")
    return mode


def format_selector(mode: str, format_id: str | None = None) -> str:
    """Build yt-dlp -f string. With format_id, pin that video stream; audio mode ignores it."""
    spec = MEDIA_MODES[mode]
    fid = (format_id or "").strip()
    if not fid or mode == "audio":
        return spec["format"]
    # DASH video usually has no audio; mux best audio when doing 音视频
    if mode == "muxed":
        return f"{fid}+ba/{fid}+bestaudio/bv*+ba/b"
    if mode == "video":
        return fid
    return spec["format"]


def download_opts_for(mode: str, outtmpl: str, hook, format_id: str | None = None) -> dict:
    spec = MEDIA_MODES[mode]
    opts = ydl_base()
    opts.update(
        {
            "format": format_selector(mode, format_id),
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "concurrent_fragment_downloads": 8,
            "retries": 5,
            "fragment_retries": 5,
        }
    )
    if spec["merge"]:
        opts["merge_output_format"] = spec["merge"]
    # 纯音频优先保留 AAC/m4a，不强制转码
    if mode == "audio":
        opts["keepvideo"] = False
    return opts


def resolve_download_path(info: dict, prepared: str, mode: str) -> str:
    for item in info.get("requested_downloads") or []:
        fp = item.get("filepath") or item.get("_filename")
        if fp and Path(fp).exists():
            return str(fp)
    p = Path(prepared)
    if p.exists():
        return str(p)
    if mode == "muxed":
        mp4 = p.with_suffix(".mp4")
        if mp4.exists():
            return str(mp4)
    parent = p.parent
    if parent.exists():
        stem = p.name.rsplit(".", 1)[0]
        cands = [
            c
            for c in parent.iterdir()
            if c.is_file()
            and c.name.startswith(stem)
            and c.suffix.lower() not in {".part", ".ytdl", ".temp", ".json"}
        ]
        cands.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        if cands:
            return str(cands[0])
    return prepared

@app.post("/api/download")
async def start_download(body: dict) -> dict:
    bvid = str(body.get("bvid") or "").strip()
    page = int(body.get("page") or 1)
    title = safe_name(str(body.get("title") or bvid))
    media = normalize_media(body.get("media") or body.get("type") or body.get("mode"))
    format_id = str(body.get("format_id") or body.get("format") or "").strip() or None
    if format_id and not re.fullmatch(r"[0-9A-Za-z._+-]+", format_id):
        raise HTTPException(400, "无效的 format_id")
    if not re.fullmatch(r"BV[0-9A-Za-z]+", bvid):
        raise HTTPException(400, "无效的 BV 号")
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "bvid": bvid,
        "page": page,
        "title": title,
        "media": media,
        "media_label": MEDIA_MODES[media]["label"],
        "format_id": format_id,
        "status": "queued",
        "progress": 0.0,
        "speed": "",
        "eta": "",
        "file": "",
        "error": "",
        "created": int(time.time()),
    }
    async with _jobs_lock:
        _jobs[job_id] = job
    asyncio.create_task(run_download(job_id))
    return job


async def run_download(job_id: str) -> None:
    job = _jobs[job_id]
    media = job.get("media") or "muxed"
    if media not in MEDIA_MODES:
        media = "muxed"
    format_id = job.get("format_id") or None
    url = video_url(job["bvid"], job["page"])
    suffix = MEDIA_MODES[media]["suffix"]
    out_root = downloads_dir()
    outfile = out_root / f"{job['title']} [{job['bvid']}]" / f"p{job['page']}{suffix}.%(ext)s"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            job["status"] = "downloading"
            job["progress"] = round(done / total * 100, 1) if total else 0
            job["speed"] = d.get("_speed_str") or ""
            job["eta"] = d.get("_eta_str") or ""
        elif d.get("status") == "finished":
            job["status"] = "muxing" if media == "muxed" else "finishing"
            job["progress"] = 100
            job["file"] = d.get("filename") or job["file"]

    opts = download_opts_for(media, str(outfile), hook, format_id=format_id)
    job["status"] = "downloading"

    def _run() -> str:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            return resolve_download_path(info, path, media)

    try:
        final = await loop.run_in_executor(None, _run)
        job["status"] = "done"
        job["progress"] = 100
        job["file"] = final
        job["speed"] = ""
        job["eta"] = ""
        history = load_json(HISTORY_PATH, [])
        history.insert(
            0,
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
            },
        )
        save_json(HISTORY_PATH, history[:100])
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


@app.get("/api/jobs")
async def jobs() -> dict:
    return {"items": list(_jobs.values())}


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@app.get("/api/history")
async def history() -> dict:
    return {"items": load_json(HISTORY_PATH, [])}


@app.get("/api/files/{job_id}")
async def download_file(job_id: str) -> FileResponse:
    history = load_json(HISTORY_PATH, [])
    match = next((x for x in history if x.get("id") == job_id), None)
    path = ""
    if match:
        path = match.get("path") or ""
    if not path:
        job = _jobs.get(job_id)
        path = (job or {}).get("file") or ""
    if not path or not Path(path).exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=Path(path).name)


@app.exception_handler(Exception)
async def fallback(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return JSONResponse({"detail": str(exc)}, status_code=500)
