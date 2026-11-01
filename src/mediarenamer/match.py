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
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path

from .parse import ParsedFile, has_cjk, normalize, read_nfo_ids
from .providers import tmdb
from .tvsources import TMDB_TV, TVMAZE, ShowCand

AUTO = 0.80
REVIEW = 0.55


def name_sim(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    la, lb = na.split(), nb.split()
    ta, tb = set(la), set(lb)
    if ta <= tb or tb <= ta:
        # subset match, discounted by how much longer the other title is:
        # 'Three Body' inside 'Three Housewives and a Body' should not score like
        # 'Monkey King' inside 'The Monkey King'. A prefix ('Frieren' for
        # 'Frieren Beyond Journeys End') is how people abbreviate, so discount less.
        short, long_ = (la, lb) if len(la) <= len(lb) else (lb, la)
        is_prefix = long_[:len(short)] == short
        contain = 0.88 * (len(short) / len(long_)) ** (0.3 if is_prefix else 0.6)
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


def anime_evidence(group: list[ParsedFile]) -> float:
    score = max((f.anime_score for f in group), default=0.0)
    if any(f.is_companion and f.path.suffix.casefold() in (".ass", ".ssa") for f in group):
        score += 0.2   # styled subtitles travel with fansubs
    return min(1.0, score)


def classify_group(group: list[ParsedFile], forced: str, folder_anime: float = 0.0) -> str:
    if forced in ("tv", "movie", "anime"):
        return forced
    strong = sum(1 for f in group if any(h.confidence >= 0.7 for h in f.episode_hints))
    bare = sum(1 for f in group if any(h.source == "bare" for h in f.episode_hints))
    is_anime = max(anime_evidence(group), folder_anime) >= 0.5
    if strong * 2 >= len(group) and strong:
        return "anime" if is_anime else "tv"
    if bare:
        if is_anime:
            return "anime"
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
    # mixed-script names ('오징어 게임 Squid Game') also search per script
    expanded: list[str] = []
    for q in out:
        for v in _title_variants(q, ""):
            if normalize(v) not in {normalize(x) for x in expanded}:
                expanded.append(v)
    return expanded[:5]


def _name_q(cand: ShowCand, queries: list[str]) -> float:
    return max((name_sim(q, n) for q in queries for n in cand.names), default=0.0)


def _score_show(cand: ShowCand, queries: list[str], years: set[int],
                ids: dict[str, str], trace: list[str], wanted: set[int] | None = None) -> float:
    best_q = _name_q(cand, queries)
    score = 0.6 * best_q
    if best_q >= 0.99:
        score += 0.15
        trace.append("  + exact title match")
    if years:
        # a year in a TV file name usually names the season's air year, not the premiere
        known = {cand.year} | {y for *_, y in (cand.seasons or []) if y}
        known.discard(None)
        if years & known:
            trace.append(f"  + year {sorted(years & known)[0]} matches premiere or a season")
            score += 0.25
        elif cand.year is not None and all(y < cand.year or y > cand.year + 25 for y in years):
            score -= 0.10   # before the show existed: contradiction
    if wanted and cand.seasons is not None:
        have = {n for n, *_ in cand.seasons}
        if wanted <= have:
            score += 0.08
            trace.append(f"  + has season {sorted(wanted)}")
        else:
            score -= 0.20
            trace.append(f"  - lacks season {sorted(wanted - have)}")
    if ids.get("tvdb") and str(cand.externals.get("thetvdb")) == str(ids["tvdb"]):
        score += 0.40
        trace.append("  + tvdb id matches path tag")
    if ids.get("imdb") and str(cand.externals.get("imdb")) == str(ids["imdb"]):
        score += 0.40
        trace.append("  + imdb id matches")
    return score


def match_tv_group(group: list[ParsedFile], season_override: int | None,
                   soft: bool, source=TVMAZE) -> list[MatchResult]:
    results = [MatchResult(file=f, kind="tv") for f in group]
    queries = _group_queries(group)
    years = _year_evidence(group)
    ids = dict(group[0].ids)
    for f in group:
        ids.update({k: v for k, v in read_nfo_ids(f.path).items() if k not in ids})

    gtrace: list[str] = [f"[{source.label}] queries: {queries}",
                         f"year evidence: {sorted(years) or 'none'}"]

    candidates: dict[int, ShowCand] = {}
    id_hit: ShowCand | None = None
    # ID evidence first — but validated, never a verdict
    if ids.get("tvdb"):
        id_hit = source.lookup_tvdb(ids["tvdb"])
        if id_hit:
            candidates[id_hit.id] = id_hit
            gtrace.append(f"tvdb-{ids['tvdb']} resolves to '{id_hit.name}'")
        else:
            gtrace.append(f"tvdb-{ids['tvdb']} is a dead ID — ignored, using name evidence")
    for q in queries:
        for s in source.search(q):
            candidates.setdefault(s.id, s)

    if not candidates:
        for r in results:
            r.trace = gtrace + ["no search results for any query"]
        return results

    wanted = {h.season for f in group for h in f.episode_hints if h.season is not None}
    if season_override is not None:
        wanted = {season_override}

    def score_all() -> list:
        out = []
        for c in candidates.values():
            tr: list[str] = []
            out.append((_score_show(c, queries, years, ids, tr, wanted), c, tr))
        out.sort(key=lambda t: -t[0])
        return out

    scored = score_all()
    # Sources with alternative titles / external ids: enrich the leaders and rescore,
    # so an alias query ('Hyakkano') can become an exact match.
    if any(not c.enriched for _, c, _ in scored[:4]) and source is not TVMAZE:
        for _, c, _ in scored[:4]:
            source.enrich(c)
        scored = score_all()
    top_s, top, top_tr = scored[0]
    margin = top_s - scored[1][0] if len(scored) > 1 else 1.0
    top_name_q = _name_q(top, queries)
    gtrace.append(f"best show: '{top.name}' ({top.year}) score={top_s:.2f} margin={margin:.2f}")
    if top.original_name and top.original_name != top.name:
        gtrace.append(f"  original title: '{top.original_name}'")
    gtrace.extend(top_tr)
    if id_hit and top.id != id_hit.id:
        gtrace.append("! path ID and name evidence disagree — review")

    seasons_needed = {h.season for f in group for h in f.episode_hints if h.season is not None}
    if any(h.season is None for f in group for h in f.episode_hints) or season_override is not None:
        seasons_needed = None   # bare numbers: need every season for the cardinality fit
    eps = source.episodes(top, seasons_needed)
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
            today = date.today().isoformat()
            aired = [s for s in fits if all(
                (s, n) in by_se and by_se[(s, n)].airdate and by_se[(s, n)].airdate <= today
                for n in bare_nums)]
            if len(by_year) == 1:
                inferred_season = by_year[0]
                gtrace.append(f"seasons {fits} all fit; year evidence selects season {inferred_season}")
            elif len(aired) == 1:
                inferred_season = aired[0]
                gtrace.append(f"seasons {fits} all fit; only season {inferred_season} has aired "
                              f"these episodes")
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
        factor = 0.95 if h.source == "bare" else 1.0   # E01 / 第01集 are explicit markers
        r.confidence = max(0.0, min(1.0, (base_conf - penalty) * factor))
    return results


# ---------------------------------------------------------------- movie matching

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _title_variants(title: str, short: str) -> list[str]:
    """Query variants for mixed-script names: full, Latin-only, CJK-only, pre-number."""
    toks = title.split()
    latin = " ".join(t for t in toks if not _CJK.search(t))
    cjk = " ".join(t for t in toks if _CJK.search(t))
    # '庆余年2' -> also try '庆余年' (sequel digit names the season, not the show)
    cjk_base = re.sub(r"(?<=[㐀-䶿一-鿿])[2-9](?=\s|$)", "", cjk) if cjk else ""
    out: list[str] = []
    for q in (title, latin, cjk, cjk_base, short):
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

_LANG_SUFFIX = re.compile(r"(?i)\.(chs|cht|sc|tc|eng?|en|jpn?|ja|zh|zh-hans|zh-hant|forced|sdh)$")


def _companion_key(p: Path) -> str:
    """'Show - 01.chs' and 'Show - 01' pair up."""
    return _LANG_SUFFIX.sub("", p.stem).casefold()


def match_all(files: list[ParsedFile], *, kind: str = "auto",
              season: int | None = None) -> list[MatchResult]:
    from .anime import match_anime_group

    def merge(primary: list[MatchResult], alt: list[MatchResult], note: str) -> list[MatchResult]:
        out_: list[MatchResult] = []
        for a, b in zip(primary, alt):
            if b.confidence > a.confidence:
                b.trace = a.trace + [note] + b.trace
                out_.append(b)
            else:
                out_.append(a)
        return out_

    def run_tv(grp: list[ParsedFile], soft: bool) -> list[MatchResult]:
        """TVmaze first for Latin titles, TMDb first for CJK titles; the second
        source is consulted whenever the first leaves anything below auto-accept."""
        cjk = any(has_cjk(q) for q in _group_queries(grp))
        order = [s for s in ([TMDB_TV, TVMAZE] if cjk else [TVMAZE, TMDB_TV]) if s.available]
        res = match_tv_group(grp, season, soft, source=order[0])
        if len(order) > 1 and not all(r.confidence >= AUTO for r in res):
            res = merge(res, match_tv_group(grp, season, soft, source=order[1]),
                        f"— also tried {order[1].label} —")
        return res

    out: list[MatchResult] = []
    groups = group_files(files)
    # folder-level anime evidence: 'Frieren 2nd Season - 05' next to fansub files is anime too
    folder_anime: dict[str, float] = defaultdict(float)
    for g in groups:
        key = str(g[0].path.parent).casefold()
        folder_anime[key] = max(folder_anime[key], anime_evidence(g))
    for group in groups:
        videos = [f for f in group if not f.is_companion]
        companions = [f for f in group if f.is_companion]
        gkind = classify_group(videos or companions, kind,
                               folder_anime[str(group[0].path.parent).casefold()])
        if gkind == "anime":
            res = match_anime_group(videos or group, season)
            if all(r.confidence < REVIEW and r.show is None for r in res):
                # AniList knew nothing; a western show with fansub-style naming
                res = merge(res, run_tv(videos or group, soft=False), "— fell back to TV providers —")
            gkind = "tv"
        elif gkind in ("tv", "tv?"):
            res = run_tv(videos or group, soft=(gkind == "tv?"))
            if kind == "auto" and all(r.confidence < REVIEW for r in res):
                # TV provider had nothing convincing; maybe it is anime without a group tag
                res = merge(res, match_anime_group(videos or group, season),
                            "— TV weak, tried anime provider —")
            gkind = "tv"
        else:
            res = [match_movie(f) for f in (videos or group)]
        # companions inherit the match of the video with the same stem, else same episode
        by_ep: dict = {}
        by_stem: dict[str, MatchResult] = {}
        for r in res:
            by_stem[_companion_key(r.file.path)] = r
            if r.kind == "tv" and r.episode is not None:
                by_ep[(r.season, r.episode)] = r
        for comp in companions:
            cr = MatchResult(file=comp, kind=gkind if gkind != "tv?" else "tv")
            hint = max(comp.episode_hints, key=lambda h: h.confidence, default=None)
            twin = by_stem.get(_companion_key(comp.path))
            if twin is None and hint and by_ep:
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
