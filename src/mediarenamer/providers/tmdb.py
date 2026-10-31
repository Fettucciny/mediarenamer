"""TMDb provider: movie search. Requires TMDB_API_KEY in the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import get_json, quote

BASE = "https://api.themoviedb.org/3"


class NoApiKey(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("TMDB_API_KEY", "").strip()
    if not k:
        raise NoApiKey("TMDB_API_KEY is not set; movie matching needs a free TMDb API key")
    return k


@dataclass
class MovieHit:
    id: int
    title: str
    original_title: str
    year: int | None          # None when TMDb has no release_date (penalized in scoring)
    popularity: float


def _to_hits(data) -> list[MovieHit]:
    out = []
    for r in (data or {}).get("results", []):
        rd = r.get("release_date") or ""
        out.append(MovieHit(
            id=r["id"], title=r.get("title") or "",
            original_title=r.get("original_title") or "",
            year=int(rd[:4]) if rd[:4].isdigit() else None,
            popularity=r.get("popularity") or 0.0,
        ))
    return out


def search_movies(query: str, year: int | None = None) -> list[MovieHit]:
    url = f"{BASE}/search/movie?api_key={_key()}&query={quote(query)}"
    if year:
        url += f"&primary_release_year={year}"
    return _to_hits(get_json(url))


def find_by_imdb(imdb_id: str) -> MovieHit | None:
    data = get_json(f"{BASE}/find/{quote(imdb_id)}?api_key={_key()}&external_source=imdb_id")
    hits = _to_hits({"results": (data or {}).get("movie_results", [])})
    return hits[0] if hits else None


def movie_by_id(tmdb_id: str) -> MovieHit | None:
    r = get_json(f"{BASE}/movie/{quote(tmdb_id)}?api_key={_key()}")
    if not r:
        return None
    rd = r.get("release_date") or ""
    return MovieHit(id=r["id"], title=r.get("title") or "",
                    original_title=r.get("original_title") or "",
                    year=int(rd[:4]) if rd[:4].isdigit() else None,
                    popularity=r.get("popularity") or 0.0)
