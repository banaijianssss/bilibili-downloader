"""全局常量与媒体模式配置。"""

from __future__ import annotations

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

# 下载队列并发上限
MAX_CONCURRENT_DOWNLOADS = 2

# B 站 API 客户端最小请求间隔（秒）
API_MIN_INTERVAL = 0.35

# Cookie 校验 / 续期间隔（秒）
LOGIN_CHECK_INTERVAL = 3600

BILI_REFRESH_PUBKEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----"""
