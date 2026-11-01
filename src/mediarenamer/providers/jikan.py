"""Jikan provider (unofficial MyAnimeList API, no key): per-episode titles.

Titles are a nicety. This module must never slow a match down: one short
attempt per request, and after the first network failure the provider is
disabled for the rest of the run.
"""
from __future__ import annotations

from . import get_json_throttled

BASE = "https://api.jikan.moe/v4"
INTERVAL = 0.5  # Jikan: 3 req/s, 60 req/min
_disabled = False


def episode_titles(mal_id: int) -> dict[int, str]:
    """Map episode number -> title for one MAL entry. Empty on failure."""
    global _disabled
    out: dict[int, str] = {}
    if _disabled:
        return out
    page = 1
    try:
        while page <= 20:
            data = get_json_throttled(f"{BASE}/anime/{mal_id}/episodes?page={page}", INTERVAL,
                                      timeout=6, attempts=1)
            if not data:
                break
            for ep in data.get("data") or []:
                n = ep.get("mal_id")
                title = ep.get("title") or ep.get("title_romanji") or ""
                if isinstance(n, int) and title:
                    out[n] = title
            if not (data.get("pagination") or {}).get("has_next_page"):
                break
            page += 1
    except Exception:
        _disabled = True   # unreachable or rate-limited: stop trying this run
    return out


def disabled_reason() -> str | None:
    return "episode-title provider (Jikan) unreachable this run" if _disabled else None
