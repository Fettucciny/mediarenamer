"""Turn match results into concrete rename operations."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .match import MatchResult

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

TV_FORMAT = "{show} - S{season:02d}E{episode:02d}{title_part}"
MOVIE_FORMAT = "{title}{year_part}"


def sanitize(name: str) -> str:
    name = re.sub(r"\s*:\s*", " - ", name)   # 'Frieren: Beyond' -> 'Frieren - Beyond'
    name = ILLEGAL.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "untitled"


@dataclass
class Op:
    src: Path
    dst: Path
    result: MatchResult


def build_plan(results: list[MatchResult], output: Path | None = None) -> list[Op]:
    ops: list[Op] = []
    taken: set[str] = set()
    for r in results:
        if r.status == "UNMATCHED":
            continue
        src = r.file.path
        if r.kind == "tv" and r.show and r.episode is not None:
            title_part = f" - {r.episode_title}" if r.episode_title else ""
            stem = TV_FORMAT.format(show=r.show, season=r.season, episode=r.episode,
                                    title_part=title_part)
            subdir = sanitize(r.show)
        elif r.kind == "movie" and r.movie_title:
            year_part = f" ({r.movie_year})" if r.movie_year else ""
            stem = MOVIE_FORMAT.format(title=r.movie_title, year_part=year_part)
            subdir = sanitize(f"{r.movie_title}{year_part}")
        else:
            continue
        stem = sanitize(stem)
        folder = (output / subdir) if output else src.parent
        dst = folder / f"{stem}{src.suffix.casefold()}"
        # collision handling: never overwrite, add a counter
        n = 1
        while str(dst).casefold() in taken or (dst.exists() and dst != src):
            n += 1
            dst = folder / f"{stem} ({n}){src.suffix.casefold()}"
        taken.add(str(dst).casefold())
        if dst != src:
            r.new_name = dst.name
            ops.append(Op(src=src, dst=dst, result=r))
    return ops
