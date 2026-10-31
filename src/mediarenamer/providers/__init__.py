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


def get_json(url: str, *, headers: dict | None = None, ok_codes: tuple = (404,)):
    """GET a JSON document with caching. Returns parsed JSON, or None on an
    'acceptable' error status (default 404). Raises on network failure."""
    cache = _load_cache()
    hit = cache.get(url)
    now = time.time()
    if hit and now - hit["ts"] < CACHE_TTL:
        return hit["data"]
    req = urllib.request.Request(url, headers={"User-Agent": "mediarenamer/0.1", **(headers or {})})
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
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


def quote(s: str) -> str:
    return urllib.parse.quote(s)
