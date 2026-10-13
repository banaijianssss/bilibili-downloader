# bilibili下载器 · Windows 版

给 Windows 10 / 11 用的哔哩检索、高画质播放和存档工具。解压后双击 `启动.bat`。解析和封装使用 yt-dlp + FFmpeg，路径和文件名按 Windows 规则处理。

## 方案调研

| 方案 | 状态 | 适合做什么 |
| --- | --- | --- |
| yt-dlp + FFmpeg | 活跃维护，本项目引擎 | DASH 分轨、4K/8K/HDR（账号有权益时）、音视频封装、分 P、字幕 |
| BBDown | 2026-05 仓库已归档 | 曾经是 B 站专用最完整的命令行下载器，含 8K / 杜比 / TV 接口，不再作为新项目底座 |
| BBDown WebUI / BBDown GUI | 依赖已归档后端 | 只有下载，没有视频和 UP 搜索 |
| you-get / lux | 维护变慢 | 简单链接可用，高画质和风控适配不如 yt-dlp |
| 在线解析站 | 不推荐 | 通常压到 720P 并重编码，隐私也不可控 |

本工作台把三件事拆开：

- 发现和搜索走哔哩公开接口（热门、WBI 视频搜索、UP 搜索、空间稿件）。
- 播放走 yt-dlp 选出的最高浏览器可解码流（优先 H.264 + AAC），经本机反代补 Referer，音视频分轨同步播放。
- 下载默认走 `bv*+ba/b`（音视频），也可选 `bv*/b` 纯视频或 `ba/b` 纯音频；多片段并发，音视频经 FFmpeg 无损封装 MP4。这是账号当前能拿到的最高画质，不经过转码。

1080P+、4K、HDR、杜比视界需要大会员 Cookie。未登录时接口通常只给 480P/720P。

## 运行

Windows：双击 `启动.bat`。首次会创建 `.venv`、安装依赖，并自动打开 `http://127.0.0.1:8787`。关闭窗口即停止。需要已安装 Python 3.11+，并勾选 Add python.exe to PATH。封装 MP4 需要 FFmpeg，可用 `winget install Gyan.FFmpeg`，或把 `ffmpeg.exe` 放在同一目录。

macOS / Linux：

```bash
cd bilibili下载器
python3 -m pip install -r requirements.txt
python3 -m uvicorn app:app --host 0.0.0.0 --port 8787
```

浏览器打开 `http://127.0.0.1:8787`。

在「账号与画质」粘贴 SESSDATA，或整段 Cookie。它只写入本机 `data/settings.json`，不会上传。

下载文件在 `downloads/`，队列里也可直接保存。

## 能力

- 热门发现、视频搜索、UP 搜索
- UP 空间优先走 yt-dlp。空间接口常返回 412 时，自动退回检索并按 mid 过滤
- BV / AV / 链接直接解析，多分 P
- 兼容最高画质播放，以及尝试绝对最高编码
- 最高画质下载（音视频 / 纯视频 / 纯音频）、进度、历史文件
- 清晰度清单：分辨率、帧率、H.264 / HEVC / AV1、码率

请只用于个人学习，以及你已获授权保存的内容。遵守哔哩哔哩用户协议和著作权法。
