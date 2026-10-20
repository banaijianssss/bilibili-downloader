"""路径与数据目录常量。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

SETTINGS_PATH = DATA / "settings.json"
HISTORY_PATH = DATA / "history.json"
JOBS_DB_PATH = DATA / "jobs.db"
COOKIES_PATH = DATA / "cookies.txt"
