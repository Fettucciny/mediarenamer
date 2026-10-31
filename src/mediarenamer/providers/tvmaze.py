"""TVmaze provider: TV series search and episode lists. No API key required."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import get_json, quote

BASE = "https://api.tvmaze.com"


@dataclass
class Show:
    id: int
    name: str
    premiered_year: int | None
    externals: dict = field(default_factory=dict)  # {'thetvdb': 123, 'imdb': 'tt..'}
    search_score: float = 0.0


@dataclass
class Episode:
    season: int
    number: int
    name: str
    airdate: str  # 'YYYY-MM-DD' or ''


def search_shows(query: str) -> list[Show]:
    data = get_json(f"{BASE}/search/shows?q={quote(query)}") or []
    out = []
    for row in data:
        s = row.get("show") or {}
        prem = s.get("premiered") or ""
        out.append(Show(
            id=s["id"], name=s.get("name") or "",
            premiered_year=int(prem[:4]) if prem[:4].isdigit() else None,
            externals={k: v for k, v in (s.get("externals") or {}).items() if v},
            search_score=row.get("score") or 0.0,
        ))
    return out


def episodes(show_id: int) -> list[Episode]:
    data = get_json(f"{BASE}/shows/{show_id}/episodes") or []
    out = []
    for e in data:
        if e.get("number") is None:  # specials without numbers
            continue
        out.append(Episode(season=e["season"], number=e["number"],
                           name=e.get("name") or "", airdate=e.get("airdate") or ""))
    return out


def lookup_by_tvdb(tvdb_id: str) -> Show | None:
    s = get_json(f"{BASE}/lookup/shows?thetvdb={quote(tvdb_id)}")
    if not s:
        return None
    prem = s.get("premiered") or ""
    return Show(id=s["id"], name=s.get("name") or "",
                premiered_year=int(prem[:4]) if prem[:4].isdigit() else None,
                externals={k: v for k, v in (s.get("externals") or {}).items() if v})


def lookup_by_imdb(imdb_id: str) -> Show | None:
    s = get_json(f"{BASE}/lookup/shows?imdb={quote(imdb_id)}")
    if not s:
        return None
    prem = s.get("premiered") or ""
    return Show(id=s["id"], name=s.get("name") or "",
                premiered_year=int(prem[:4]) if prem[:4].isdigit() else None,
                externals={k: v for k, v in (s.get("externals") or {}).items() if v})
