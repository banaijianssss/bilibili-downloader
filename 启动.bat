@echo off
setlocal EnableExtensions EnableDelayedExpansion
title bilibili下载器
cd /d "%~dp0"

echo.
echo  ========================================
echo            bilibili下载器
echo  ========================================
echo.

set "PORT=8787"
if defined LUMINA_PORT set "PORT=%LUMINA_PORT%"
set "HOST=127.0.0.1"
if defined LUMINA_HOST set "HOST=%LUMINA_HOST%"

set "VPY=%~dp0.venv\Scripts\python.exe"

rem --- prefer existing venv; else find system Python ---
if exist "%VPY%" (
  echo  [1/3] 已有虚拟环境 .venv
  goto :deps
)

set "PY="
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PY=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo  [错误] 未找到 Python 3。
  echo         请安装 Python 3.11 或更高版本，
  echo         安装时勾选 Add python.exe to PATH。
  echo         下载: https://www.python.org/downloads/windows/
  echo.
  pause
  exit /b 1
)

echo  [1/3] 正在创建虚拟环境 .venv ...
%PY% -m venv .venv
if errorlevel 1 (
  echo  [错误] 虚拟环境创建失败。
  echo         确认已安装 Python 3.11+，且安装时勾选了 venv。
  pause
  exit /b 1
)

:deps
echo  [2/3] 正在检查依赖 ...
"%VPY%" -m pip install --disable-pip-version-check -q -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo  [错误] 依赖安装失败。请检查网络后重新双击本脚本。
  pause
  exit /b 1
)

if exist "%~dp0ffmpeg.exe" set "PATH=%~dp0;%PATH%"
if exist "%~dp0bin\ffmpeg.exe" set "PATH=%~dp0bin;%PATH%"
if not exist "%~dp0downloads" mkdir "%~dp0downloads"
if not exist "%~dp0data" mkdir "%~dp0data"

set "FFOK=0"
where ffmpeg >nul 2>&1 && set "FFOK=1"
if exist "%~dp0ffmpeg.exe" set "FFOK=1"
if exist "%~dp0bin\ffmpeg.exe" set "FFOK=1"
if "!FFOK!"=="0" (
  echo.
  echo  [重要] 未检测到 FFmpeg！
  echo         没有 FFmpeg 时：播放/解析仍可用，但「音视频」下载无法封装成 MP4。
  echo         请先安装后再启动：
  echo           winget install Gyan.FFmpeg
  echo         或将 ffmpeg.exe 放到本目录 / bin 目录。
  echo         安装完成后重新双击本脚本即可。
  echo.
) else (
  echo  [提示] 已检测到 FFmpeg，下载会自动封装 MP4。
)
echo  [提示] 下载队列会保存在 data\jobs.db，关闭后可继续排队任务。

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo  [提示] 端口 %PORT% 已被占用，改为 8788。
  set "PORT=8788"
)

echo.
echo  ----------------------------------------
echo  [3/3] 启动服务
echo         地址: http://%HOST%:%PORT%
echo         关闭本窗口即停止服务
echo         下载目录: downloads
echo  ----------------------------------------
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://%HOST%:%PORT%/"
"%VPY%" -m uvicorn app:app --host %HOST% --port %PORT%
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo  [错误] 服务异常退出，代码 %RC%。
  pause
)
exit /b %RC%
