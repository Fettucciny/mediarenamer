"""Turn match results into concrete rename operations.

Naming schemes (chosen in settings):
  tv    'plex'     -> Show (Year) - S01E02 - Episode Title        (FileBot {plex.id} file part)
        'simple'   -> Show - S01E02 - Episode Title
  movie 'filebot'  -> Title.With.Dots (Year)[.lang] [Director] 1080p.x265-GROUP
                      (FileBot {n.upperInitial().space('.')} ({y}){subt} [{director}] {vf}.{vc}{'-'+group})
        'simple'   -> Title (Year)

Files stay where they are unless an output folder is given. A dropped folder
that holds exactly one show is renamed to 'Show {tvdb-ID}' (no year), so a
later run can re-identify it from the ID alone. Every movie ends in a folder
named exactly like its video file: the movie's own folder is renamed to that,
and a loose movie gets a new subfolder created around it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .match import MatchResult
from .parse import STRUCTURAL_FOLDERS, VIDEO_EXTS, normalize
from .probe import probe
from .providers import tmdb

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TV_SCHEMES = ("plex", "simple")
MOVIE_SCHEMES = ("filebot", "simple")

_LANG_MAP = {"en": "eng", "eng": "eng", "english": "eng", "chs": "chs", "sc": "chs", "zh-hans": "chs",
             "cht": "cht", "tc": "cht", "zh-hant": "cht", "zh": "chi", "chi": "chi", "ja": "jpn",
             "jp": "jpn", "jpn": "jpn", "ko": "kor", "kor": "kor", "forced": "forced", "sdh": "sdh"}


def sanitize(name: str) -> str:
    name = re.sub(r"\s*:\s*", " - ", name)   # 'Frieren: Beyond' -> 'Frieren - Beyond'
    name = ILLEGAL.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "untitled"


def dotted(title: str) -> str:
    """FileBot n.upperInitial().space('.'): capitalize each word's first letter, dots for spaces."""
    t = ILLEGAL.sub("", title.replace("&", "and"))
    words = [w[:1].upper() + w[1:] for w in t.split()]
    return ".".join(words).strip(".")


def subtitle_suffix(path: Path) -> str:
    """'.chs' / '.eng' for subtitle companions ('Show - 01.chs.ass'), '' for videos."""
    if path.suffix.casefold() not in (".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"):
        return ""
    m = re.search(r"\.([A-Za-z-]{2,7})$", path.stem)
    if not m:
        return ""
    tag = m.group(1).casefold()
    return "." + _LANG_MAP[tag] if tag in _LANG_MAP else ""


_director_cache: dict[int, str | None] = {}


def _director(tmdb_id: int | None) -> str | None:
    if not tmdb_id:
        return None
    if tmdb_id not in _director_cache:
        try:
            _director_cache[tmdb_id] = tmdb.movie_director(tmdb_id)
        except Exception:
            _director_cache[tmdb_id] = None
    return _director_cache[tmdb_id]


def tv_stem(r: MatchResult, scheme: str, prefer_original: bool) -> str:
    show = r.show_original if prefer_original and r.show_original else (r.show or "")
    year = f" ({r.show_year})" if scheme == "plex" and r.show_year else ""
    title_part = f" - {r.episode_title}" if r.episode_title else ""
    return sanitize(f"{show}{year} - S{r.season:02d}E{r.episode:02d}{title_part}")


def movie_stem(r: MatchResult, scheme: str, prefer_original: bool) -> str:
    title = r.movie_original if prefer_original and r.movie_original else (r.movie_title or "")
    year_part = f" ({r.movie_year})" if r.movie_year else ""
    if scheme != "filebot":
        return sanitize(f"{title}{year_part}")
    stem = f"{dotted(title)}{year_part}{subtitle_suffix(r.file.path)}"
    director = _director(r.tmdb_id)
    if director:
        stem += f" [{sanitize(director)}]"
    vf, vc = probe(r.file.path)
    tech = ".".join(x for x in (vf, vc) if x)
    if tech:
        stem += f" {tech}"
    if r.file.release_group:
        stem += f"-{r.file.release_group}"
    return sanitize(stem)


def title_key(r: MatchResult):
    """What a section / folder is 'about': one database entry (or normalized title).

    Different providers know the same show under different ids (TVmaze has no
    TMDb id, TMDb has no TVmaze id), so comparing single keys splits one show
    into several. Use title_groups() to compare across results; this returns
    one representative key for display and fallback bucketing.
    """
    toks = _identity_tokens(r)
    return toks[0] if toks else None


def _identity_tokens(r: MatchResult) -> list[tuple] | None:
    """Every identity this result is known by: each database id, plus the
    normalized (title, year). Two results that share any token are one title."""
    if r.status == "UNMATCHED" or r.kind not in ("tv", "movie"):
        return None
    toks: list[tuple] = []
    if r.kind == "tv":
        ids = r.show_ids or {}
        for k in ("tmdb", "tvdb", "anilist", "mal", "tvmaze", "imdb"):
            if ids.get(k):
                toks.append(("tv", k, str(ids[k])))
        if r.show:
            toks.append(("tv", "name", normalize(r.show), str(r.show_year or "")))
    else:
        if r.tmdb_id:
            toks.append(("movie", "tmdb", str(r.tmdb_id)))
        if r.movie_title:
            toks.append(("movie", "name", normalize(r.movie_title), str(r.movie_year or "")))
    return toks or None


def title_groups(results: list[MatchResult]) -> dict[int, tuple]:
    """Map id(result) -> canonical title key, merging results that share any
    database id or the same normalized (title, year) across providers."""
    parent: dict[tuple, tuple] = {}

    def find(x: tuple) -> tuple:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    toks_of: dict[int, list[tuple]] = {}
    for r in results:
        toks = _identity_tokens(r)
        if not toks:
            continue
        toks_of[id(r)] = toks
        for t in toks:
            parent.setdefault(t, t)
        for t in toks[1:]:
            ra, rb = find(toks[0]), find(t)
            if ra != rb:
                parent[rb] = ra

    # one deterministic key per merged group: the smallest token in it
    members: dict[tuple, set] = {}
    for toks in toks_of.values():
        members.setdefault(find(toks[0]), set()).update(toks)
    canon = {root: min(ts) for root, ts in members.items()}
    return {rid: canon[find(toks[0])] for rid, toks in toks_of.items()}


def folder_name(r: MatchResult, prefer_original: bool = False) -> str:
    """TV folder form: 'Show {tvdb-123}' (name and database id, no year)."""
    if r.kind == "tv":
        name = r.show_original if prefer_original and r.show_original else r.show
        ids = r.show_ids or {}
    else:
        name = r.movie_original if prefer_original and r.movie_original else r.movie_title
        ids = {"tmdb": r.tmdb_id} if r.tmdb_id else {}
    out = sanitize(name or "")
    for k in ("tmdb", "tvdb", "anilist", "tvmaze", "imdb"):
        if ids.get(k):
            out += f" {{{k}-{ids[k]}}}"
            break
    return out


@dataclass
class Op:
    src: Path
    dst: Path
    result: MatchResult | None


def _movie_plan(results: list[MatchResult], groups: dict[int, tuple], movie_scheme: str,
                prefer_original: bool, rename_roots: list[Path] | None):
    """Every movie ends in a folder named like its video file.

    Returns (target_dir_by_result_id, parent_renames). For each (parent dir,
    movie) pair: when the parent holds only that movie, sits inside a dropped
    root and is not a structural name (Movies, Downloads, ...), the parent is
    renamed to the video's stem; otherwise a subfolder with that stem is
    created next to the file and the movie's files move into it.
    """
    roots = [r for r in (rename_roots or []) if r.is_dir()]
    keys_in_parent: dict[Path, set] = {}
    unmatched_parent: set[Path] = set()
    for r in results:
        p = r.file.path.parent
        if id(r) in groups:
            keys_in_parent.setdefault(p, set()).add(groups[id(r)])
        else:
            unmatched_parent.add(p)

    by_pk: dict[tuple[Path, tuple], list[MatchResult]] = {}
    for r in results:
        key = groups.get(id(r))
        if key and key[0] == "movie":
            by_pk.setdefault((r.file.path.parent, key), []).append(r)

    target: dict[int, Path] = {}
    renames: list[tuple[Path, Path]] = []
    for (parent, key), rs in by_pk.items():
        video = next((x for x in rs if x.file.path.suffix.casefold() in VIDEO_EXTS), None)
        if video is None:
            continue
        stem = sanitize(movie_stem(video, movie_scheme, prefer_original))
        if not stem:
            continue
        sole_title = (keys_in_parent.get(parent) == {key} and parent not in unmatched_parent
                      and not _other_videos_on_disk(parent, rs))
        in_roots = any(_is_under(parent, root) for root in roots)
        structural = bool(STRUCTURAL_FOLDERS.match(parent.name))
        if sole_title and in_roots and not structural and parent.parent != parent:
            for x in rs:
                target[id(x)] = parent
            dst = parent.with_name(stem)
            if dst != parent and not dst.exists():
                renames.append((parent, dst))
        else:
            for x in rs:
                target[id(x)] = parent / stem
    return target, renames


def _other_videos_on_disk(parent: Path, group: list[MatchResult]) -> bool:
    """True when the folder holds video files that are not this movie's own —
    the ground truth guard against renaming a shared folder after one movie.
    Structural subfolders (Sample, Subs, Extras...) are the movie's own."""
    ours = {str(r.file.path).casefold() for r in group}
    try:
        for child in parent.iterdir():
            if child.is_file():
                if child.suffix.casefold() in VIDEO_EXTS and str(child).casefold() not in ours:
                    return True
            elif child.is_dir() and not STRUCTURAL_FOLDERS.match(child.name):
                if any(g.suffix.casefold() in VIDEO_EXTS for g in child.glob("*")):
                    return True
    except OSError:
        return True
    return False


def build_plan(results: list[MatchResult], output: Path | None = None,
               prefer_original: bool = False, tv_scheme: str = "plex",
               movie_scheme: str = "filebot", rename_roots: list[Path] | None = None) -> list[Op]:
    """Compute target paths and set r.new_name. Files stay in place unless `output`
    is given. A folder in `rename_roots` holding exactly one show is renamed to
    'Show {tvdb-ID}'; movie folders are created or renamed by _movie_plan."""
    ops: list[Op] = []
    taken: set[str] = set()
    groups = title_groups(results)
    movie_target, movie_renames = ({}, []) if output else _movie_plan(
        results, groups, movie_scheme, prefer_original, rename_roots)
    for r in results:
        if r.status == "UNMATCHED":
            continue
        src = r.file.path
        if r.kind == "tv" and r.show and r.episode is not None:
            stem = tv_stem(r, tv_scheme, prefer_original)
            subdir = sanitize(r.show_original if prefer_original and r.show_original else r.show)
        elif r.kind == "movie" and r.movie_title:
            stem = movie_stem(r, movie_scheme, prefer_original)
            subdir = folder_name(r, prefer_original)
        else:
            continue
        if output:
            folder = output / subdir
        else:
            folder = movie_target.get(id(r), src.parent)
        dst = folder / f"{stem}{src.suffix.casefold()}"
        n = 1
        while str(dst).casefold() in taken or (dst.exists() and dst != src):
            n += 1
            dst = folder / f"{stem} ({n}){src.suffix.casefold()}"
        taken.add(str(dst).casefold())
        if dst != src:
            r.new_name = dst.name if dst.parent == src.parent else f"{dst.parent.name}\\{dst.name}"
            ops.append(Op(src=src, dst=dst, result=r))
        else:
            r.new_name = src.name

    for src_dir, dst_dir in movie_renames:
        ops.append(Op(src=src_dir, dst=dst_dir, result=None))

    for root in rename_roots or []:
        if output or not root.is_dir() or root.parent == root:
            continue
        inside = [r for r in results if id(r) in groups and _is_under(r.file.path, root)]
        keys = {groups[id(r)] for r in inside}
        if len(keys) != 1 or next(iter(keys))[0] != "tv":
            continue   # movie folders are handled by _movie_plan
        new_name = folder_name(inside[0], prefer_original)
        dst = root.parent / new_name
        if new_name and dst != root and not dst.exists():
            ops.append(Op(src=root, dst=dst, result=None))
    return ops


def planned_folder_name(results: list[MatchResult], root: Path, prefer_original: bool = False,
                        movie_scheme: str = "filebot") -> str | None:
    groups = title_groups(results)
    inside = [r for r in results if id(r) in groups and _is_under(r.file.path, root)]
    keys = {groups[id(r)] for r in inside}
    if len(keys) != 1:
        return None
    if next(iter(keys))[0] == "movie":
        _, renames = _movie_plan(results, groups, movie_scheme, prefer_original, [root])
        for src_dir, dst_dir in renames:
            if _is_under(src_dir, root):
                return dst_dir.name
        return None
    name = folder_name(inside[0], prefer_original)
    return name if name and name != root.name else None


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False
