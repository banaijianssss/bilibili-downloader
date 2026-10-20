"""冒烟测试：不访问真实 B 站网络。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bili.wbi import mixin_key, sign_wbi
from jobs import db as jobs_db
from media.ytdlp_util import format_selector, host_allowed, normalize_media, safe_name


def test_safe_name_strips_windows_illegal():
    assert ":" not in safe_name('a:b/c*d?"<>|')
    assert safe_name("CON").startswith("_")
    assert safe_name("") == "video"
    assert len(safe_name("x" * 200)) <= 80


def test_host_allowed():
    assert host_allowed("https://upos-sz-mirrorcos.bilivideo.com/foo")
    assert host_allowed("https://i0.hdslb.com/bfs/archive/x.jpg")
    assert not host_allowed("https://evil.example.com/x")
    assert not host_allowed("not-a-url")


def test_normalize_media():
    assert normalize_media("muxed") == "muxed"
    assert normalize_media("音视频") == "muxed"
    assert normalize_media("video") == "video"
    assert normalize_media("纯音频") == "audio"
    with pytest.raises(Exception):
        normalize_media("bogus")


def test_format_selector():
    assert format_selector("muxed") == "bv*+ba/b"
    assert "100" in format_selector("muxed", "100")
    assert format_selector("video", "30080") == "30080"
    assert format_selector("audio", "100") == "ba/b"


def test_wbi_mixin_fixed_input():
    # 固定输入，不依赖网络
    key = mixin_key("7a625540c76d48b78d8f4f21a14e6b8c", "b4b8a6f3c9e14c9e8d1f2a3b4c5d6e7f")
    assert isinstance(key, str)
    assert len(key) == 32
    signed = sign_wbi({"keyword": "test", "page": 1}, key)
    assert "wts" in signed
    assert "w_rid" in signed
    assert len(signed["w_rid"]) == 32


def test_jobs_db_crud(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    jobs_db.close_db()
    jobs_db.init_db(db_path)
    job = jobs_db.create_job(bvid="BVtest000001", page=1, title="hello", media="muxed", media_label="音视频")
    assert job["status"] == "queued"
    assert jobs_db.get_job(job["id"])["bvid"] == "BVtest000001"
    jobs_db.update_job(job["id"], status="running", progress=10.5)
    assert jobs_db.get_job(job["id"])["progress"] == 10.5
    claimed = jobs_db.claim_next_queued()
    # already running, nothing queued
    assert claimed is None
    job2 = jobs_db.create_job(bvid="BVtest000002", page=2, title="p2")
    claimed = jobs_db.claim_next_queued()
    assert claimed is not None
    assert claimed["id"] == job2["id"]
    assert claimed["status"] == "running"
    jobs_db.update_job(job["id"], status="error", error="fail")
    retried = jobs_db.reset_for_retry(job["id"])
    assert retried["status"] == "queued"
    n = jobs_db.recover_on_startup()
    assert n >= 1  # claimed job2 was running
    assert jobs_db.get_job(job2["id"])["status"] == "interrupted"
    jobs_db.close_db()
