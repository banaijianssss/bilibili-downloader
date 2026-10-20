"""B 站 WBI 签名。"""

from __future__ import annotations

import hashlib
import time
import urllib.parse
from typing import Any

from config import MIXIN_KEY_ENC_TAB

_wbi_cache: dict[str, Any] = {"key": "", "exp": 0.0}


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def sign_wbi(params: dict, mixin: str) -> dict:
    signed = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in params.items()}
    signed["wts"] = int(time.time())
    signed = dict(sorted(signed.items()))
    query = urllib.parse.urlencode(signed)
    signed["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return signed


def clear_wbi_cache() -> None:
    _wbi_cache["key"] = ""
    _wbi_cache["exp"] = 0.0


def get_cached_mixin() -> str | None:
    now = time.time()
    if _wbi_cache["key"] and _wbi_cache["exp"] > now:
        return _wbi_cache["key"]
    return None


def set_cached_mixin(key: str, ttl: float = 1800) -> None:
    _wbi_cache["key"] = key
    _wbi_cache["exp"] = time.time() + ttl
