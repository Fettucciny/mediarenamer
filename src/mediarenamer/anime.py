"""Anime matching: fansub names, synonyms, and absolute numbering across seasons.

AniList stores each season as its own entry linked by PREQUEL/SEQUEL relations.
We resolve the best entry, walk to the root of its chain, and map episode
numbers either locally (n <= entry.episodes) or absolutely across the chain.
"""
from __future__ import annotations

import re

from .match import AUTO, REVIEW, MatchResult, _group_queries, _year_evidence, name_sim
from .parse import ParsedFile, SEASON_WORD_RE, normalize
from .providers import anilist, jikan

_TRAILING_SEASON = re.compile(
    r"(?i)[\s:\-]*(?:(?:\d{1,2}(?:st|nd|rd|th)\s+)?season(?:\s+\d{1,2})?|part\s+\d|\bs\d{1,2}|"
    r"\d{1,2}(?:st|nd|rd|th)\s+season|final\s+season|cour\s+\d)\s*$")


def _series_name_of(name: str) -> str:
    stripped = _TRAILING_SEASON.sub("", name).strip(" -:")
    return stripped or name


def _series_name(root: anilist.Anime) -> str:
    return _series_name_of(root.display_name)


def _chain(top: anilist.Anime, trace: list[str]) -> list[anilist.Anime]:
    """Root-first list of TV-format entries linked by sequel relations."""
    seen = {top.id}
    root = top
    for _ in range(10):
        if not root.prequel_ids:
            break
        pre = anilist.get(root.prequel_ids[0])
        if not pre or pre.id in seen:
            break
        seen.add(pre.id)
        root = pre
    chain = [root]
    cur = root
    for _ in range(15):
        if not cur.sequel_ids:
            break
        nxt = anilist.get(cur.sequel_ids[0])
        if not nxt or nxt.id in seen:
            break
        seen.add(nxt.id)
        chain.append(nxt)
        cur = nxt
    if len(chain) > 1:
        trace.append("season chain: " + " -> ".join(
            f"S{i + 1} '{a.display_name}' ({a.episodes or '?'} eps)" for i, a in enumerate(chain)))
    return chain


def _score(c: anilist.Anime, queries: list[str], years: set[int], nums: list[int],
           multi: bool, tr: list[str]) -> float:
    best = max((name_sim(q, n) for q in queries for n in c.names), default=0.0)
    s = 0.6 * best
    if best >= 0.99:
        s += 0.15
        tr.append("  + exact title/synonym match")
    if c.year is not None and years:
        if c.year in years:
            s += 0.2
            tr.append(f"  + year {c.year} confirmed")
        else:
            s -= 0.05
    if multi and c.is_series:
        s += 0.05
    if c.format == "MOVIE" and nums:
        s -= 0.2
    if c.format in ("ONA", "OVA", "SPECIAL") and not any(
            re.search(r"(?i)\b(ona|ova|special|sp)\b", q) for q in queries):
        s -= 0.08   # side content rarely is what a plain-named file refers to
    if nums and c.episodes and max(nums) <= c.episodes:
        s += 0.08
    if not c.prequel_ids and c.is_series:
        s += 0.04   # root entries are what folders are usually named after
    return s


def match_anime_group(group: list[ParsedFile], season_override: int | None) -> list[MatchResult]:
    results = [MatchResult(file=f, kind="tv") for f in group]
    queries = _group_queries(group)
    years = _year_evidence(group)
    nums = sorted({h.episode for f in group for h in f.episode_hints})
    multi = len(group) > 1
    gtrace: list[str] = [f"anime queries: {queries}", f"year evidence: {sorted(years) or 'none'}"]

    cands: dict[int, anilist.Anime] = {}
    ids = group[0].ids
    for key in ("anilist",):
        if ids.get(key):
            hit = anilist.get(int(ids[key]))
            if hit:
                cands[hit.id] = hit
                gtrace.append(f"anilist-{ids[key]} resolves to '{hit.display_name}'")
    for q in queries:
        for c in anilist.search(q):
            cands.setdefault(c.id, c)
    if not cands:
        for r in results:
            r.trace = gtrace + ["no AniList results for any query"]
        return results

    scored = []
    for c in cands.values():
        tr: list[str] = []
        scored.append((_score(c, queries, years, nums, multi, tr), c, tr))
    scored.sort(key=lambda t: -t[0])
    top_s, top, top_tr = scored[0]
    top_q = max((name_sim(q, n) for q in queries for n in top.names), default=0.0)
    gtrace.append(f"best entry: '{top.display_name}' ({top.year}, {top.format}, "
                  f"{top.episodes or '?'} eps) score={top_s:.2f}")
    gtrace.extend(top_tr)

    chain = _chain(top, gtrace) if top.is_series else [top]
    chain_ids = {a.id for a in chain}
    root_name = chain[0].display_name

    def same_franchise(c: anilist.Anime) -> bool:
        return c.id in chain_ids or max(
            (name_sim(root_name, n) for n in c.names), default=0.0) >= 0.6

    rivals = [s for s, c, _ in scored[1:] if not same_franchise(c)]
    margin = top_s - rivals[0] if rivals else 1.0

    base = min(0.95, 0.5 + 0.4 * top_s)
    if top_q < 0.55:
        base = min(base, REVIEW - 0.05)
        gtrace.append(f"! no entry matches the title well (best similarity {top_q:.2f})")
    if margin < 0.1:
        base -= 0.15
        gtrace.append("! close unrelated candidate — confidence reduced")

    series = _series_name(chain[0])
    titles_cache: dict[int, dict[int, str]] = {}

    def titles_for(a: anilist.Anime) -> dict[int, str]:
        if a.id not in titles_cache:
            titles_cache[a.id] = jikan.episode_titles(a.mal_id) if a.mal_id else {}
        return titles_cache[a.id]

    top_index = next((i for i, a in enumerate(chain) if a.id == top.id), 0)

    for r in results:
        r.trace = list(gtrace)
        hints = sorted(r.file.episode_hints, key=lambda h: -h.confidence)
        if not hints:
            r.trace.append("no episode number found in file name")
            continue
        h = hints[0]
        entry: anilist.Anime | None = None
        ep = h.episode
        factor = 1.0 if h.source in ("sxxeyy", "nxnn") else 0.95
        season_no = season_override if season_override is not None else h.season
        if season_no is not None:
            if 1 <= season_no <= len(chain):
                entry = chain[season_no - 1]
            else:
                r.trace.append(f"season {season_no} not in known chain of {len(chain)}")
        elif top.episodes and ep <= top.episodes:
            entry = top
            factor = 1.0   # bare numbers are the anime convention; a local fit is not weak
        else:
            # absolute numbering across the chain, counted from the root
            acc = 0
            for a in chain:
                n_eps = a.episodes or 0
                if n_eps and ep <= acc + n_eps:
                    entry, ep = a, ep - acc
                    break
                acc += n_eps
            if entry is not None:
                factor *= 0.95
                r.trace.append(f"absolute {h.episode} -> season {chain.index(entry) + 1} episode {ep}")
            else:
                r.trace.append(f"episode {h.episode} exceeds all {acc} known episodes")
        if entry is None:
            r.confidence = min(base, REVIEW - 0.05)
            continue
        if entry.episodes and ep > entry.episodes:
            r.trace.append(f"episode {ep} exceeds {entry.episodes} episodes of '{entry.display_name}'")
            r.confidence = min(base, REVIEW - 0.05)
            continue
        r.show = series
        r.show_original = _series_name_of(chain[0].romaji or chain[0].native) if (
            chain[0].romaji or chain[0].native) else None
        r.show_year = chain[0].year
        r.show_ids = {k: v for k, v in {"anilist": chain[0].id, "mal": chain[0].mal_id}.items() if v}
        r.season = chain.index(entry) + 1 if entry.id in chain_ids else (top_index + 1)
        r.episode = ep
        r.episode_title = titles_for(entry).get(ep)
        if r.episode_title is None and jikan.disabled_reason():
            r.trace.append(jikan.disabled_reason())
        r.confidence = max(0.0, min(1.0, base * factor))
    return results
