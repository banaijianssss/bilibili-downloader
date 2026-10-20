"""bilibili下载器 — Windows 本地检索、高画质播放与存档。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import login as auth_login
from bili.client import close_client
from jobs import queue as job_queue
from media.proxy import router as proxy_router
from paths import STATIC
from routes.auth import router as auth_router
from routes.discover import router as discover_router
from routes.health import bind_info_cache, router as health_router
from routes.jobs import router as jobs_router
from routes.video import get_info_cache, router as video_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    bind_info_cache(get_info_cache())
    await job_queue.start_worker()
    await auth_login.start_login_watcher()
    try:
        yield
    finally:
        await auth_login.stop_login_watcher()
        await job_queue.stop_worker()
        await close_client()


app = FastAPI(title="bilibili下载器", version="1.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_cache(request: Request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(discover_router)
app.include_router(video_router)
app.include_router(jobs_router)
app.include_router(proxy_router)


@app.exception_handler(Exception)
async def fallback(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return JSONResponse({"detail": str(exc)}, status_code=500)
