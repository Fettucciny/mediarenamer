"""Batch matcher: groups files, gathers evidence, scores candidates, explains itself.

Confidence bands:
  >= AUTO   : safe to rename automatically
  >= REVIEW : plausible, shown as REVIEW, applied only with --accept-review
  <  REVIEW : unmatched, with reasons
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .parse import ParsedFile, normalize, read_nfo_ids
from .providers import tmdb, tvmaze

AUTO = 0.80
REVIEW = 0.55


def name_sim(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta <= tb or tb <= ta:
        # subset match, discounted by how much longer the other title is:
        # 'Three Body' inside 'Three Housewives and a Body' should not score like
        # 'Monkey King' inside 'The Monkey King'
        contain = 0.88 * (min(len(ta), len(tb)) / max(len(ta), len(tb))) ** 0.6
    else:
        contain = 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    jacc = len(ta & tb) / len(ta | tb)
    return max(contain, 0.7 * ratio + 0.3 * jacc)


@dataclass
class MatchResult:
    file: ParsedFile
    kind: str                   # 'tv' | 'movie' | 'skip'
    confidence: float = 0.0
    new_name: str | None = None  # filled by planner
    trace: list[str] = field(default_factory=list)
    # tv fields
    show: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    # movie fields
    movie_title: str | None = None
    movie_year: int | None = None
    tmdb_id: int | None = None

    @property
    def status(self) -> str:
        if self.confidence >= AUTO:
            return "AUTO"
        if self.confidence >= REVIEW:
            return "REVIEW"
        return "UNMATCHED"


# ---------------------------------------------------------------- grouping

def group_files(files: list[ParsedFile]) -> list[list[ParsedFile]]:
    """Group by (parent folder, normalized file title). Files with no title of
    their own fall into the folder-wide group — they inherit the folder title."""
    groups: dict[tuple, list[ParsedFile]] = defaultdict(list)
    for f in files:
        key = (str(f.path.parent).casefold(), normalize(f.title))
        groups[key].append(f)
    return list(groups.values())


def classify_group(group: list[ParsedFile], forced: str) -> str:
    if forced in ("tv", "movie"):
        return forced
    strong = sum(1 for f in group if any(h.confidence >= 0.7 for h in f.episode_hints))
    bare = sum(1 for f in group if any(h.source == "bare" for h in f.episode_hints))
    if strong * 2 >= len(group) and strong:
        return "tv"
    if bare:
        nums = sorted({h.episode for f in group for h in f.episode_hints if h.source == "bare"})
        # several small sequential-ish numbers -> almost certainly episodes
        if len(nums) >= 2 and nums[-1] - nums[0] <= len(nums) * 3 and nums[-1] <= 300:
            return "tv"
        f0 = group[0]
        if len(group) == 1 and nums and nums[0] <= 100 and not (f0.years or f0.folder_years):
            return "tv?"      # single file, weak evidence: try TV but cap confidence
        # a lone file with a year and a small number ('Ne Zha 2 2025') is a movie sequel
    return "movie"


# ---------------------------------------------------------------- TV matching

def _year_evidence(group: list[ParsedFile]) -> set[int]:
    ys: set[int] = set()
    for f in group:
        ys.update(f.years)
        ys.update(f.folder_years)
    return ys


def _group_queries(group: list[ParsedFile]) -> list[str]:
    """Candidate search terms: most common file title, then folder titles.
    Structural folders were already filtered at parse time."""
    out: list[str] = []
    titles = Counter(f.title for f in group if f.title)
    if titles:
        out.append(titles.most_common(1)[0][0])
    folder = Counter(t for f in group for t in f.folder_titles[:1])
    if folder:
        t = folder.most_common(1)[0][0]
        if normalize(t) not in {normalize(x) for x in out}:
            out.append(t)
    return out


def _score_show(cand: tvmaze.Show, queries: list[str], years: set[int],
                ids: dict[str, str], trace: list[str]) -> float:
    best_q = max((name_sim(q, cand.name) for q in queries), default=0.0)
    score = 0.6 * best_q
    if best_q >= 0.99:
        score += 0.15
        trace.append("  + exact title match")
    if cand.premiered_year is not None and years:
        if cand.premiered_year in years:
            score += 0.25
            trace.append(f"  + year {cand.premiered_year} confirmed by name/path")
        else:
            score -= 0.10
    if ids.get("tvdb") and str(cand.externals.get("thetvdb")) == str(ids["tvdb"]):
        score += 0.40
        trace.append("  + tvdb id matches path tag")
    if ids.get("imdb") and str(cand.externals.get("imdb")) == str(ids["imdb"]):
        score += 0.40
        trace.append("  + imdb id matches")
    return score


def match_tv_group(group: list[ParsedFile], season_override: int | None,
                   soft: bool) -> list[MatchResult]:
    results = [MatchResult(file=f, kind="tv") for f in group]
    queries = _group_queries(group)
    years = _year_evidence(group)
    ids = dict(group[0].ids)
    for f in group:
        ids.update({k: v for k, v in read_nfo_ids(f.path).items() if k not in ids})

    gtrace: list[str] = [f"queries: {queries}", f"year evidence: {sorted(years) or 'none'}"]

    candidates: dict[int, tvmaze.Show] = {}
    # ID evidence first — but validated, never a verdict
    if ids.get("tvdb"):
        hit = tvmaze.lookup_by_tvdb(ids["tvdb"])
        if hit:
            candidates[hit.id] = hit
            gtrace.append(f"tvdb-{ids['tvdb']} resolves to '{hit.name}'")
        else:
            gtrace.append(f"tvdb-{ids['tvdb']} is a dead ID — ignored, using name evidence")
    for q in queries:
        for s in tvmaze.search_shows(q):
            candidates.setdefault(s.id, s)

    if not candidates:
        for r in results:
            r.trace = gtrace + ["no search results for any query"]
        return results

    scored = []
    for c in candidates.values():
        tr: list[str] = []
        s = _score_show(c, queries, years, ids, tr)
        scored.append((s, c, tr))
    scored.sort(key=lambda t: -t[0])
    top_s, top, top_tr = scored[0]
    margin = top_s - scored[1][0] if len(scored) > 1 else 1.0
    top_name_q = max((name_sim(q, top.name) for q in queries), default=0.0)
    gtrace.append(f"best show: '{top.name}' ({top.premiered_year}) score={top_s:.2f} margin={margin:.2f}")
    gtrace.extend(top_tr)
    if ids.get("tvdb") and str(top.externals.get("thetvdb")) not in (str(ids["tvdb"]), "None") \
            and tvmaze.lookup_by_tvdb(ids["tvdb"]):
        gtrace.append("! path ID and name evidence disagree — review")

    eps = tvmaze.episodes(top.id)
    by_se = {(e.season, e.number): e for e in eps}
    season_counts: dict[int, int] = Counter()
    for e in eps:
        season_counts[e.season] = max(season_counts[e.season], e.number)
    abs_order = sorted(eps, key=lambda e: (e.season, e.number))

    # season inference for bare/season-less numbers: cardinality fit
    bare_nums = sorted({h.episode for f in group for h in f.episode_hints if h.season is None})
    inferred_season: int | None = season_override
    season_conf_penalty = 0.0
    if inferred_season is None and bare_nums:
        fits = [s for s, mx in sorted(season_counts.items()) if s > 0 and max(bare_nums) <= mx]
        if len(fits) == 1:
            inferred_season = fits[0]
            gtrace.append(f"episode numbers {bare_nums} fit only season {inferred_season}")
        elif len(fits) > 1:
            # try airdate-year evidence to break the tie
            by_year = [s for s in fits if any(
                by_se[(s, n)].airdate[:4].isdigit() and int(by_se[(s, n)].airdate[:4]) in years
                for n in bare_nums if (s, n) in by_se)]
            if len(by_year) == 1:
                inferred_season = by_year[0]
                gtrace.append(f"seasons {fits} all fit; year evidence selects season {inferred_season}")
            else:
                inferred_season = fits[0]
                season_conf_penalty = 0.12
                gtrace.append(f"! numbers fit seasons {fits}; defaulting to season {fits[0]} — "
                              f"REVIEW, use --season to override")
        elif max(bare_nums) <= len(abs_order):
            gtrace.append(f"numbers exceed every season; interpreting as absolute order")
            inferred_season = -1  # sentinel: absolute
        else:
            gtrace.append(f"! numbers {bare_nums} exceed all {len(abs_order)} episodes of '{top.name}'")

    base_conf = min(0.95, 0.5 + 0.4 * top_s)
    if top_name_q < 0.55 and not any(
            str(top.externals.get(k2)) == str(v2) for k2, v2 in
            [("thetvdb", ids.get("tvdb")), ("imdb", ids.get("imdb"))] if v2):
        base_conf = min(base_conf, REVIEW - 0.05)
        gtrace.append(f"! no candidate matches the title well (best similarity "
                      f"{top_name_q:.2f}) — likely an alias this provider does not know")
    if margin < 0.1:
        base_conf -= 0.15
        gtrace.append(f"! close second candidate '{scored[1][1].name}' — confidence reduced")
    if soft:
        base_conf = min(base_conf, REVIEW + 0.1)

    for r in results:
        r.trace = list(gtrace)
        hints = sorted(r.file.episode_hints, key=lambda h: -h.confidence)
        if not hints:
            r.trace.append("no episode number found in file name")
            r.confidence = 0.0
            continue
        h = hints[0]
        se: tuple[int, int] | None = None
        penalty = 0.0
        if h.season is not None:
            se = (h.season, h.episode)
        elif inferred_season == -1:
            if 1 <= h.episode <= len(abs_order):
                e = abs_order[h.episode - 1]
                se = (e.season, e.number)
                r.trace.append(f"absolute {h.episode} -> S{e.season:02d}E{e.number:02d}")
        elif inferred_season is not None:
            se = (inferred_season, h.episode)
            penalty = season_conf_penalty   # only files that rely on the guessed season pay
        if se is None or se not in by_se:
            r.trace.append(f"episode {se or h.episode} not found in '{top.name}'")
            r.confidence = min(base_conf, REVIEW - 0.05)
            continue
        ep = by_se[se]
        r.show, r.season, r.episode = top.name, se[0], se[1]
        r.episode_title = ep.name
        factor = 1.0 if h.source in ("sxxeyy", "nxnn") else 0.95
        r.confidence = max(0.0, min(1.0, (base_conf - penalty) * factor))
    return results


# ---------------------------------------------------------------- movie matching

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _title_variants(title: str, short: str) -> list[str]:
    """Query variants for mixed-script names: full, Latin-only, CJK-only, pre-number."""
    toks = title.split()
    latin = " ".join(t for t in toks if not _CJK.search(t))
    cjk = " ".join(t for t in toks if _CJK.search(t))
    out: list[str] = []
    for q in (title, latin, cjk, short):
        if q and normalize(q) and normalize(q) not in {normalize(x) for x in out}:
            out.append(q)
    return out


def match_movie(f: ParsedFile) -> MatchResult:
    r = MatchResult(file=f, kind="movie")
    title = f.title_full or f.title or (f.folder_titles[0] if f.folder_titles else "")
    if not title:
        r.trace.append("no title tokens found in name or path")
        return r
    queries = _title_variants(title, f.title)
    years = list(dict.fromkeys(f.years + f.folder_years))
    ids = dict(f.ids)
    ids.update({k: v for k, v in read_nfo_ids(f.path).items() if k not in ids})
    r.trace.append(f"queries: {queries}, years: {years or 'none'}")

    try:
        candidates: list[tmdb.MovieHit] = []
        id_hit: tmdb.MovieHit | None = None
        if ids.get("tmdb"):
            id_hit = tmdb.movie_by_id(ids["tmdb"])
        elif ids.get("imdb"):
            id_hit = tmdb.find_by_imdb(ids["imdb"])
        if id_hit:
            # Validate the ID against name/year evidence instead of trusting it
            sim = max(name_sim(q, t) for q in queries for t in (id_hit.title, id_hit.original_title))
            year_ok = (not years) or (id_hit.year in years)
            if sim >= 0.6 and year_ok:
                r.movie_title, r.movie_year, r.tmdb_id = id_hit.title, id_hit.year, id_hit.id
                r.confidence = 0.95
                r.trace.append(f"ID evidence confirmed by name/year: '{id_hit.title}' ({id_hit.year})")
                return r
            r.trace.append(f"! ID points to '{id_hit.title}' ({id_hit.year}) but name/year evidence "
                           f"disagrees (sim={sim:.2f}, year_ok={year_ok}) — falling back to search")
        for q in queries:
            for y in years or [None]:
                candidates += tmdb.search_movies(q, y)
            if years:
                candidates += tmdb.search_movies(q)  # year might be wrong; keep net wide
    except tmdb.NoApiKey as e:
        r.trace.append(str(e))
        return r

    seen: set[int] = set()
    best: tuple[float, tmdb.MovieHit] | None = None
    second = 0.0
    for c in candidates:
        if c.id in seen:
            continue
        seen.add(c.id)
        sim = max(name_sim(q, t) for q in queries for t in (c.title, c.original_title))
        s = 0.6 * sim
        if c.year is not None and years:
            s += 0.3 if c.year in years else -0.1
        if c.year is None:
            s -= 0.1   # TMDb entry without release date: weak citizen
        s += min(c.popularity, 50.0) / 50.0 * 0.05   # popularity: tie-break only
        if best is None or s > best[0]:
            second = best[0] if best else 0.0
            best = (s, c)
        elif s > second:
            second = s
    if best is None:
        r.trace.append("no TMDb results for any query")
        return r
    s, c = best
    r.movie_title, r.movie_year, r.tmdb_id = c.title, c.year, c.id
    conf = min(1.0, 0.35 + s)
    r.trace.append(f"best: '{c.title}' ({c.year}) tmdb-{c.id} score={s:.2f}")
    best_sim = max(name_sim(q, t) for q in queries for t in (c.title, c.original_title))
    if best_sim < 0.55:
        conf = min(conf, REVIEW - 0.05)
        r.trace.append(f"! no candidate matches the title well (best similarity {best_sim:.2f})")
    if not years:
        conf = min(conf, AUTO - 0.01)
        r.trace.append("no year evidence anywhere — capped below auto-accept")
    elif len(f.years) > 1:
        conf = min(conf, AUTO - 0.01)
        r.trace.append(f"several years in the name {f.years} — capped below auto-accept")
    if s - second < 0.08:
        conf -= 0.1
        r.trace.append("close competing candidate — confidence reduced")
    r.confidence = max(0.0, conf)
    return r


# ---------------------------------------------------------------- entry point

def match_all(files: list[ParsedFile], *, kind: str = "auto",
              season: int | None = None) -> list[MatchResult]:
    out: list[MatchResult] = []
    for group in group_files(files):
        videos = [f for f in group if not f.is_companion]
        companions = [f for f in group if f.is_companion]
        gkind = classify_group(videos or group, kind)
        if gkind in ("tv", "tv?"):
            res = match_tv_group(videos or group, season, soft=(gkind == "tv?"))
        else:
            res = [match_movie(f) for f in (videos or group)]
        # companions inherit the match of the video with the same episode/stem
        by_ep: dict = {}
        for r in res:
            if r.kind == "tv" and r.episode is not None:
                by_ep[(r.season, r.episode)] = r
        for comp in companions:
            cr = MatchResult(file=comp, kind=gkind if gkind != "tv?" else "tv")
            hint = max(comp.episode_hints, key=lambda h: h.confidence, default=None)
            twin = None
            if hint and by_ep:
                twin = by_ep.get((hint.season, hint.episode)) or next(
                    (v for (s, e), v in by_ep.items() if e == hint.episode), None)
            if twin:
                cr.__dict__.update({k: v for k, v in twin.__dict__.items()
                                    if k in ("show", "season", "episode", "episode_title",
                                             "movie_title", "movie_year", "tmdb_id",
                                             "confidence", "kind")})
                cr.trace = ["companion: inherits match from video file"]
            else:
                cr.trace = ["companion file with no matching video twin"]
            out.append(cr)
        out.extend(res)
    return out
