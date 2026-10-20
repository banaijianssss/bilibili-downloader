"""settings / history 原子读写。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from paths import HISTORY_PATH, SETTINGS_PATH

_settings_lock = asyncio.Lock()
_history_file_lock = threading.Lock()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    """先写临时文件再 rename，避免并发写坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_json(path: Path, data: Any) -> None:
    atomic_write_json(path, data)


def settings() -> dict:
    data = load_json(SETTINGS_PATH, {})
    data.setdefault("sessdata", "")
    data.setdefault("cookie", "")
    return data


async def update_settings(mutator) -> dict:
    """在锁内读取、修改并写回 settings。mutator(s) -> None。"""
    async with _settings_lock:
        s = settings()
        mutator(s)
        save_json(SETTINGS_PATH, s)
        return s


def cookie_header() -> str:
    s = settings()
    raw = (s.get("cookie") or "").strip()
    if raw:
        return raw
    sess = (s.get("sessdata") or "").strip()
    if sess:
        return f"SESSDATA={sess}"
    return ""


def append_history(entry: dict, limit: int = 100) -> None:
    with _history_file_lock:
        history = load_json(HISTORY_PATH, [])
        if not isinstance(history, list):
            history = []
        history.insert(0, entry)
        save_json(HISTORY_PATH, history[:limit])


def load_history() -> list:
    with _history_file_lock:
        data = load_json(HISTORY_PATH, [])
        return data if isinstance(data, list) else []


def settings_lock() -> asyncio.Lock:
    return _settings_lock
