"""디스크 캐시 + 재시도 HTTP. 프록시 환경변수는 requests 가 자동 적용한다."""
import hashlib
import time
from pathlib import Path

import requests

from .config import HTTP_RETRIES, HTTP_TIMEOUT, RAW

UA = {"User-Agent": "Mozilla/5.0 (etf-pipeline; research use)"}


class FetchError(RuntimeError):
    pass


def _cache_path(url: str, data=None) -> Path:
    key = url + ("|" + repr(sorted(data.items())) if data else "")
    return RAW / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".bin")


def fetch(url: str, *, data=None, headers=None, refresh=False, session=None) -> bytes:
    """GET(data 없음)/POST(data 있음). refresh=True 면 캐시를 무시하고 재조회."""
    cp = _cache_path(url, data)
    if cp.exists() and not refresh:
        return cp.read_bytes()
    s = session or requests
    last = None
    for i in range(HTTP_RETRIES):
        try:
            h = {**UA, **(headers or {})}
            r = s.post(url, data=data, headers=h, timeout=HTTP_TIMEOUT) if data \
                else s.get(url, headers=h, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            RAW.mkdir(parents=True, exist_ok=True)
            cp.write_bytes(r.content)
            return r.content
        except requests.RequestException as e:  # 403(프록시 차단)/타임아웃 모두 포함
            last = e
            time.sleep(2 ** i)
    raise FetchError(f"{url}: {last}")
