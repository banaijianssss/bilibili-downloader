"""登录相关路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from auth import login as auth_login

router = APIRouter()


@router.get("/api/login/qr")
async def login_qr() -> dict:
    return await auth_login.login_qr()


@router.get("/api/login/qr/poll")
async def login_qr_poll(key: str = Query(min_length=8, max_length=64)) -> dict:
    return await auth_login.login_qr_poll(key)


@router.get("/api/login/status")
async def login_status() -> dict:
    return await auth_login.ensure_login_fresh()


@router.post("/api/login/logout")
async def login_logout() -> dict:
    return await auth_login.login_logout()
