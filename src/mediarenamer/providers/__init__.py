"""HTTP helpers and a small on-disk JSON cache shared by all providers."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE_DIR = Path.home() / ".mediarenamer"
CACHE_FILE = CACHE_DIR / "cache.json"
CACHE_TTL = 7 * 24 * 3600
_cache: dict | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
    except OSError:
        pass


def get_json(url: str, *, headers: dict | None = None, ok_codes: tuple = (404,),
             timeout: float = 20, attempts: int = 3):
    """GET a JSON document with caching. Returns parsed JSON, or None on an
    'acceptable' error status (default 404). Raises on network failure."""
    cache = _load_cache()
    hit = cache.get(url)
    now = time.time()
    if hit and now - hit["ts"] < CACHE_TTL:
        return hit["data"]
    req = urllib.request.Request(url, headers={"User-Agent": "mediarenamer/0.1", **(headers or {})})
    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cache[url] = {"ts": now, "data": data}
            _save_cache()
            return data
        except urllib.error.HTTPError as e:
            if e.code in ok_codes:
                cache[url] = {"ts": now, "data": None}
                _save_cache()
                return None
            if e.code == 429:
                time.sleep(2 * (attempt + 1))
                last_err = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"request failed after retries: {url}: {last_err}")


def post_json(url: str, payload: dict, *, min_interval: float = 0.0):
    """POST JSON with caching keyed on url+payload. `min_interval` throttles
    uncached calls (seconds between requests to the same host)."""
    cache = _load_cache()
    key = url + "|" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    hit = cache.get(key)
    now = time.time()
    if hit and now - hit["ts"] < CACHE_TTL:
        return hit["data"]
    _throttle(url, min_interval)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": "mediarenamer/0.1", "Content-Type": "application/json",
        "Accept": "application/json"})
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cache[key] = {"ts": now, "data": data}
            _save_cache()
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (attempt + 1))
                last_err = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"request failed after retries: {url}: {last_err}")


_last_call: dict[str, float] = {}


def _throttle(url: str, min_interval: float) -> None:
    if min_interval <= 0:
        return
    host = urllib.parse.urlsplit(url).netloc
    wait = _last_call.get(host, 0.0) + min_interval - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.time()


def get_json_throttled(url: str, min_interval: float, **kw):
    cache = _load_cache()
    hit = cache.get(url)
    if not (hit and time.time() - hit["ts"] < CACHE_TTL):
        _throttle(url, min_interval)
    return get_json(url, **kw)


def quote(s: str) -> str:
    return urllib.parse.quote(s)
