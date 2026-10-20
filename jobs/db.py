"""下载任务 SQLite 持久化。"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from paths import JOBS_DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    bvid TEXT NOT NULL,
    page INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    media TEXT NOT NULL DEFAULT 'muxed',
    media_label TEXT NOT NULL DEFAULT '',
    format_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    speed TEXT NOT NULL DEFAULT '',
    eta TEXT NOT NULL DEFAULT '',
    file TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    subs INTEGER NOT NULL DEFAULT 1,
    cover INTEGER NOT NULL DEFAULT 1,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created DESC);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    global _conn
    path = db_path or JOBS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if _conn is None:
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def init_db(db_path: Path | None = None) -> None:
    with _lock:
        global _conn
        if db_path is not None:
            if _conn is not None:
                try:
                    _conn.close()
                except Exception:
                    pass
            _conn = None
        _connect(db_path)


def close_db() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["subs"] = bool(d.get("subs", 1))
    d["cover"] = bool(d.get("cover", 1))
    try:
        d["extra"] = json.loads(d.get("extra") or "{}")
    except Exception:
        d["extra"] = {}
    return d


def create_job(
    *,
    bvid: str,
    page: int = 1,
    title: str = "",
    media: str = "muxed",
    media_label: str = "",
    format_id: str | None = None,
    subs: bool = True,
    cover: bool = True,
    extra: dict | None = None,
    job_id: str | None = None,
) -> dict:
    jid = job_id or uuid.uuid4().hex[:12]
    now = int(time.time())
    row = {
        "id": jid,
        "bvid": bvid,
        "page": page,
        "title": title,
        "media": media,
        "media_label": media_label,
        "format_id": format_id,
        "status": "queued",
        "progress": 0.0,
        "speed": "",
        "eta": "",
        "file": "",
        "error": "",
        "created": now,
        "updated": now,
        "subs": 1 if subs else 0,
        "cover": 1 if cover else 0,
        "extra": json.dumps(extra or {}, ensure_ascii=False),
    }
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT INTO jobs
            (id,bvid,page,title,media,media_label,format_id,status,progress,speed,eta,file,error,created,updated,subs,cover,extra)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["id"], row["bvid"], row["page"], row["title"], row["media"], row["media_label"],
                row["format_id"], row["status"], row["progress"], row["speed"], row["eta"],
                row["file"], row["error"], row["created"], row["updated"], row["subs"], row["cover"], row["extra"],
            ),
        )
        conn.commit()
    return get_job(jid)  # type: ignore[return-value]


def get_job(job_id: str) -> dict | None:
    with _lock:
        conn = _connect()
        cur = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def list_jobs(limit: int = 200) -> list[dict]:
    with _lock:
        conn = _connect()
        cur = conn.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))
        return [_row_to_dict(r) for r in cur.fetchall()]


def update_job(job_id: str, **fields: Any) -> dict | None:
    if not fields:
        return get_job(job_id)
    allowed = {
        "status", "progress", "speed", "eta", "file", "error",
        "title", "media", "media_label", "format_id", "page", "subs", "cover", "extra",
    }
    sets = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("subs", "cover"):
            v = 1 if v else 0
        if k == "extra" and isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return get_job(job_id)
    sets.append("updated=?")
    vals.append(int(time.time()))
    vals.append(job_id)
    with _lock:
        conn = _connect()
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
    return get_job(job_id)


def claim_next_queued() -> dict | None:
    """原子领取下一个 queued 任务，标为 running。"""
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created ASC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        jid = row["id"]
        now = int(time.time())
        conn.execute(
            "UPDATE jobs SET status='running', updated=? WHERE id=? AND status='queued'",
            (now, jid),
        )
        if conn.total_changes == 0:
            conn.commit()
            return None
        conn.commit()
        cur = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,))
        claimed = cur.fetchone()
        return _row_to_dict(claimed) if claimed else None


def recover_on_startup() -> int:
    """进程重启：running -> interrupted；queued 保留。返回 interrupted 数量。"""
    with _lock:
        conn = _connect()
        now = int(time.time())
        cur = conn.execute(
            "UPDATE jobs SET status='interrupted', error=COALESCE(NULLIF(error,''), '进程中断，可重试'), updated=? WHERE status IN ('running','downloading','muxing','finishing')",
            (now,),
        )
        conn.commit()
        return cur.rowcount


def count_active() -> int:
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status IN ('running','downloading','muxing','finishing')"
        )
        return int(cur.fetchone()["c"])


def reset_for_retry(job_id: str) -> dict | None:
    job = get_job(job_id)
    if not job:
        return None
    if job["status"] not in ("error", "interrupted", "cancelled"):
        return None
    return update_job(
        job_id,
        status="queued",
        progress=0,
        speed="",
        eta="",
        error="",
        file=job.get("file") or "",
    )
