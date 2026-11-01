"""AniList provider (GraphQL, no key). Titles, synonyms, episode counts and
sequel/prequel relations — the data needed to resolve fansub names and
absolute numbering across seasons."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import post_json

URL = "https://graphql.anilist.co"
INTERVAL = 0.8  # AniList allows ~30-90 req/min; stay polite

_FIELDS = """
  id idMal format episodes seasonYear
  startDate { year }
  title { romaji english native }
  synonyms
  relations { edges { relationType node { id format } } }
"""


@dataclass
class Anime:
    id: int
    mal_id: int | None
    format: str              # TV, TV_SHORT, ONA, OVA, MOVIE, SPECIAL, ...
    episodes: int | None
    year: int | None
    romaji: str
    english: str
    native: str
    synonyms: list[str] = field(default_factory=list)
    prequel_ids: list[int] = field(default_factory=list)
    sequel_ids: list[int] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [n for n in [self.english, self.romaji, self.native, *self.synonyms] if n]

    @property
    def display_name(self) -> str:
        return self.english or self.romaji or self.native

    @property
    def is_series(self) -> bool:
        return self.format in ("TV", "TV_SHORT", "ONA")


def _to_anime(m: dict) -> Anime:
    rel = (m.get("relations") or {}).get("edges") or []
    seq, pre = [], []
    for e in rel:
        node = e.get("node") or {}
        if node.get("format") in ("TV", "TV_SHORT", "ONA"):
            if e.get("relationType") == "SEQUEL":
                seq.append(node["id"])
            elif e.get("relationType") == "PREQUEL":
                pre.append(node["id"])
    t = m.get("title") or {}
    return Anime(
        id=m["id"], mal_id=m.get("idMal"), format=m.get("format") or "",
        episodes=m.get("episodes"),
        year=m.get("seasonYear") or (m.get("startDate") or {}).get("year"),
        romaji=t.get("romaji") or "", english=t.get("english") or "", native=t.get("native") or "",
        synonyms=[s for s in (m.get("synonyms") or []) if s],
        prequel_ids=pre, sequel_ids=seq,
    )


def search(query: str, per_page: int = 10) -> list[Anime]:
    q = "query($s:String,$n:Int){Page(page:1,perPage:$n){media(search:$s,type:ANIME,sort:SEARCH_MATCH){" + _FIELDS + "}}}"
    data = post_json(URL, {"query": q, "variables": {"s": query, "n": per_page}}, min_interval=INTERVAL)
    media = ((data or {}).get("data") or {}).get("Page", {}).get("media") or []
    return [_to_anime(m) for m in media]


def get(anime_id: int) -> Anime | None:
    q = "query($id:Int){Media(id:$id,type:ANIME){" + _FIELDS + "}}"
    data = post_json(URL, {"query": q, "variables": {"id": anime_id}}, min_interval=INTERVAL)
    m = ((data or {}).get("data") or {}).get("Media")
    return _to_anime(m) if m else None
