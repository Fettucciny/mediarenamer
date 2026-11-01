"""Uniform TV data sources so the matcher can run over TVmaze or TMDb TV.

TVmaze: no key, strong for western shows, thin for Asian dramas.
TMDb TV: needs TMDB_API_KEY, strong for Chinese / Korean / Japanese titles and
alternative titles in every script.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .providers import tmdb, tvmaze


@dataclass
class ShowCand:
    id: int
    name: str
    names: list[str]                      # every title/alias we know for scoring
    year: int | None
    externals: dict = field(default_factory=dict)   # {'thetvdb': .., 'imdb': ..}
    source: str = ""
    original_name: str = ""
    seasons: list[tuple[int, int, int | None]] | None = None  # [(season, episode_count, air_year)]
    enriched: bool = False


@dataclass
class Ep:
    season: int
    number: int
    name: str
    airdate: str


class TVmazeSource:
    label = "TVmaze"
    available = True

    @staticmethod
    def _c(s: tvmaze.Show) -> ShowCand:
        return ShowCand(id=s.id, name=s.name, names=[s.name], year=s.premiered_year,
                        externals={"thetvdb": s.externals.get("thetvdb"),
                                   "imdb": s.externals.get("imdb")}, source="TVmaze")

    def search(self, q: str) -> list[ShowCand]:
        return [self._c(s) for s in tvmaze.search_shows(q)]

    def lookup_tvdb(self, tvdb_id: str) -> ShowCand | None:
        s = tvmaze.lookup_by_tvdb(tvdb_id)
        return self._c(s) if s else None

    def enrich(self, c: ShowCand) -> ShowCand:
        return c

    def episodes(self, c: ShowCand, seasons: set[int] | None = None) -> list[Ep]:
        return [Ep(e.season, e.number, e.name, e.airdate) for e in tvmaze.episodes(c.id)]


class TMDbTVSource:
    label = "TMDb"

    @property
    def available(self) -> bool:
        return bool(os.environ.get("TMDB_API_KEY", "").strip())

    @staticmethod
    def _c(h: tmdb.TvHit) -> ShowCand:
        names = [n for n in (h.name, h.original_name) if n]
        return ShowCand(id=h.id, name=h.name or h.original_name, names=names, year=h.year,
                        source="TMDb", original_name=h.original_name)

    def search(self, q: str) -> list[ShowCand]:
        return [self._c(h) for h in tmdb.search_tv(q)]

    def lookup_tvdb(self, tvdb_id: str) -> ShowCand | None:
        h = tmdb.find_tv_by_tvdb(tvdb_id)
        return self.enrich(self._c(h)) if h else None

    def enrich(self, c: ShowCand) -> ShowCand:
        if c.enriched:
            return c
        d = tmdb.tv_details(c.id)
        if d:
            for t in d.alt_titles:
                if t and t not in c.names:
                    c.names.append(t)
            c.externals = {"thetvdb": d.tvdb_id, "imdb": d.imdb_id}
            c.seasons = d.seasons
            c.year = c.year or d.year
        c.enriched = True
        return c

    def episodes(self, c: ShowCand, seasons: set[int] | None = None) -> list[Ep]:
        self.enrich(c)
        out: list[Ep] = []
        for n, *_ in (c.seasons or [])[:15]:
            if n <= 0 or (seasons is not None and n not in seasons):
                continue
            for e in tmdb.tv_season(c.id, n):
                out.append(Ep(n, e["episode_number"], e.get("name") or "", e.get("air_date") or ""))
        return out


TVMAZE = TVmazeSource()
TMDB_TV = TMDbTVSource()
