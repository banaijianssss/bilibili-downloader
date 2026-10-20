"""yt-dlp 抽取、清晰度选择、FFmpeg 探测。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import HTTPException

from config import MEDIA_MODES
from paths import COOKIES_PATH, ROOT, SETTINGS_PATH
from settings_store import cookie_header, load_json


def default_user_downloads() -> Path:
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / "Downloads"


def downloads_dir() -> Path:
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


def cookiefile() -> str | None:
    header = cookie_header()
    if not header:
        return None
    lines = ["# Netscape HTTP Cookie File"]
    for part in header.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{name.strip()}\t{value.strip()}")
    COOKIES_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(COOKIES_PATH)


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


def stream_label(video: dict | None) -> str:
    if not video:
        return "无可用流"
    fps = f"{int(video['fps'])}帧" if video.get("fps") else ""
    height = f"{video['height']}P" if video.get("height") else video.get("note") or "未知"
    return " ".join(x for x in (height, fps, video.get("codec")) if x)


def ydl_base() -> dict:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 20,
        "retries": 3,
        "windowsfilenames": True,
        "continuedl": True,
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


def normalize_media(raw: str | None) -> str:
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
    spec = MEDIA_MODES[mode]
    fid = (format_id or "").strip()
    if not fid or mode == "audio":
        return spec["format"]
    if mode == "muxed":
        return f"{fid}+ba/{fid}+bestaudio/bv*+ba/b"
    if mode == "video":
        return fid
    return spec["format"]


def download_opts_for(
    mode: str,
    outtmpl: str,
    hook,
    format_id: str | None = None,
    *,
    subs: bool = True,
    cover: bool = True,
) -> dict:
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
            "continuedl": True,
        }
    )
    if spec["merge"]:
        opts["merge_output_format"] = spec["merge"]
    if mode == "audio":
        opts["keepvideo"] = False
    if subs:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["zh-CN", "zh-Hans", "zh-TW", "zh", "ai-zh", "en"]
        opts["subtitlesformat"] = "srt/best"
    if cover:
        opts["writethumbnail"] = True
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


def host_allowed(url: str) -> bool:
    import urllib.parse
    from config import CDN_SUFFIXES

    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return any(host == s or host.endswith("." + s) for s in CDN_SUFFIXES)
