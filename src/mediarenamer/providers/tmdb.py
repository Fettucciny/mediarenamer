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


# ------------------------------------------------------------------ TV

@dataclass
class TvHit:
    id: int
    name: str
    original_name: str
    year: int | None
    popularity: float


@dataclass
class TvDetails:
    id: int
    name: str
    original_name: str
    year: int | None
    alt_titles: list[str]
    tvdb_id: int | None
    imdb_id: str | None
    seasons: list[tuple[int, int, int | None]]   # (season_number, episode_count, air_year)


def _tv_hits(results) -> list[TvHit]:
    out = []
    for r in results or []:
        fd = r.get("first_air_date") or ""
        out.append(TvHit(id=r["id"], name=r.get("name") or "", original_name=r.get("original_name") or "",
                         year=int(fd[:4]) if fd[:4].isdigit() else None,
                         popularity=r.get("popularity") or 0.0))
    return out


def search_tv(query: str, year: int | None = None) -> list[TvHit]:
    url = f"{BASE}/search/tv?api_key={_key()}&query={quote(query)}"
    if year:
        url += f"&first_air_date_year={year}"
    return _tv_hits((get_json(url) or {}).get("results"))


def find_tv_by_tvdb(tvdb_id: str) -> TvHit | None:
    data = get_json(f"{BASE}/find/{quote(tvdb_id)}?api_key={_key()}&external_source=tvdb_id")
    hits = _tv_hits((data or {}).get("tv_results"))
    return hits[0] if hits else None


def tv_details(tv_id: int) -> TvDetails | None:
    d = get_json(f"{BASE}/tv/{tv_id}?api_key={_key()}&append_to_response=alternative_titles,external_ids")
    if not d:
        return None
    fd = d.get("first_air_date") or ""
    alts = [a.get("title") for a in (d.get("alternative_titles") or {}).get("results", [])]
    ext = d.get("external_ids") or {}
    return TvDetails(
        id=d["id"], name=d.get("name") or "", original_name=d.get("original_name") or "",
        year=int(fd[:4]) if fd[:4].isdigit() else None,
        alt_titles=[a for a in alts if a],
        tvdb_id=ext.get("tvdb_id"), imdb_id=ext.get("imdb_id"),
        seasons=[(s.get("season_number"), s.get("episode_count") or 0,
                  int((s.get("air_date") or "")[:4]) if (s.get("air_date") or "")[:4].isdigit() else None)
                 for s in d.get("seasons") or [] if s.get("season_number") is not None],
    )


def tv_season(tv_id: int, season: int) -> list[dict]:
    d = get_json(f"{BASE}/tv/{tv_id}/season/{season}?api_key={_key()}")
    return (d or {}).get("episodes") or []


def movie_by_id(tmdb_id: str) -> MovieHit | None:
    r = get_json(f"{BASE}/movie/{quote(tmdb_id)}?api_key={_key()}")
    if not r:
        return None
    rd = r.get("release_date") or ""
    return MovieHit(id=r["id"], title=r.get("title") or "",
                    original_title=r.get("original_title") or "",
                    year=int(rd[:4]) if rd[:4].isdigit() else None,
                    popularity=r.get("popularity") or 0.0)
