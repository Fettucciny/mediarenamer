"""Filename and path parsing: extract title, years, episode hypotheses, IDs.

Everything extracted is *evidence* with a confidence, never a verdict.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
              ".webm", ".mpg", ".mpeg", ".m4v"}
COMPANION_EXTS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}

# Words that are release metadata, never part of a title once seen.
RELEASE_TAGS = {
    "480p", "576p", "720p", "1080p", "2160p", "4320p", "4k", "8k", "uhd",
    "bluray", "blu", "ray", "bdrip", "brrip", "remux", "webrip", "web", "dl",
    "webdl", "hdtv", "dvdrip", "dvd", "hdrip", "cam", "ts",
    "x264", "x265", "h264", "h265", "avc", "hevc", "av1", "xvid", "divx",
    "10bit", "8bit", "hdr", "hdr10", "dovi", "dv", "sdr",
    "aac", "ac3", "eac3", "dts", "truehd", "atmos", "flac", "mp3", "opus",
    "dd5", "ddp5", "5.1", "7.1", "2.0",
    "repack", "proper", "rerip", "internal", "limited", "extended", "uncut",
    "unrated", "remastered", "remaster", "imax", "complete", "multi", "dual",
    "subbed", "dubbed", "sub", "subs", "nf", "amzn", "dsnp", "hulu", "atvp",
    "max", "viutv", "gb", "cht", "chs", "big5",
}
RESOLUTION_NUMBERS = {"480", "576", "720", "1080", "2160", "4320"}

# Folder names that are structure, never titles.
STRUCTURAL_FOLDERS = re.compile(
    r"(?i)^(season[ ._-]?\d+|s\d{1,2}|specials?|extras?|featurettes?|samples?|"
    r"subs?|subtitles?|downloads?|torrents?|complete|collection|videos?|movies?|"
    r"films?|tv|series|anime|media|new folder|temp|tmp|incoming|unsorted|misc|other|"
    r"字幕|caseb|bdmv|video_ts)$")

YEAR_TOKEN = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
MIN_YEAR, MAX_YEAR = 1920, date.today().year + 1   # 2049 is a title word, not a year


def is_year(tok: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d\d", tok)) and MIN_YEAR <= int(tok) <= MAX_YEAR


def find_years(s: str) -> list[int]:
    return [int(y) for y in YEAR_TOKEN.findall(s) if MIN_YEAR <= int(y) <= MAX_YEAR]


class _YearRe:
    """Drop-in for the old regex object: fullmatch/findall with range filtering."""
    @staticmethod
    def fullmatch(tok: str):
        return is_year(tok) or None

    @staticmethod
    def findall(s: str) -> list[str]:
        return [str(y) for y in find_years(s)]


YEAR_RE = _YearRe()
SXXEYY_RE = re.compile(r"(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]?e(\d{1,3})(?:-?e?(\d{1,3}))?(?![0-9])")
NXNN_RE = re.compile(r"(?i)(?<![a-z0-9(])(\d{1,2})x(\d{2,3})(?![0-9])")
EXX_RE = re.compile(r"(?i)(?<![a-z0-9])(?:e|ep|episode)[ ._]?(\d{1,3})(?![0-9])")
BARE_NUM_RE = re.compile(r"(?<![\w(])(\d{1,3})(?:v\d)?(?![\w)])")
BRACKET_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
ID_RE = re.compile(r"(?i)\{?(tmdb|tvdb|imdb|anilist|mal)[-=:]((?:tt)?\d+)\}?")
IMDB_RE = re.compile(r"(?i)(?<![a-z0-9])(tt\d{7,8})(?![0-9])")
CRC_RE = re.compile(r"^[A-Fa-f0-9]{8}$")
CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# 'Frieren 2nd Season - 05', 'Show Season 2 - 05', 'Show S2 - 05'
SEASON_WORD_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?:(\d{1,2})(?:st|nd|rd|th)[ ]+season|season[ ]+(\d{1,2})|s(\d{1,2}))(?![a-z0-9])")
KNOWN_ANIME_GROUPS = {
    "subsplease", "erai-raws", "horriblesubs", "judas", "ember", "asw", "skymoon-raws",
    "nekomoe kissaten", "lolihouse", "ani", "sakurato", "lilith-raws", "nc-raws", "vcb-studio",
    "commie", "kametsu", "yameii", "tsundere-raws", "ohys-raws", "moozzi2", "beatrice-raws",
    "anime time", "reinforce", "gjm", "doki", "coalgirls", "underwater", "fff", "vivid",
    "damedesuyo", "sallysubs", "exiled-destiny", "utw", "chihiro", "comicat", "romanticat",
    "sweetsub", "kamigami", "dmhy", "mingy", "haruhana", "sbsub", "billion meta lab",
    "nan-raws", "hysub", "ktxp", "jibaketa", "orion", "seed-raws", "trix", "varyg", "toonshub",
}


def normalize(s: str) -> str:
    """Casefold, strip diacritics and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.casefold())
    return " ".join(s.split())


@dataclass
class EpisodeHint:
    season: int | None      # None = unknown season
    episode: int
    confidence: float       # how certain this token is an episode marker
    source: str             # 'sxxeyy' | 'nxnn' | 'exx' | 'bare'


@dataclass
class ParsedFile:
    path: Path
    title: str                                 # title before the first episode marker ('' if none)
    title_full: str = ""                       # title ignoring bare numbers (movie view: 'Ne Zha 2')
    years: list[int] = field(default_factory=list)       # all plausible years, name first then path
    episode_hints: list[EpisodeHint] = field(default_factory=list)
    folder_titles: list[str] = field(default_factory=list)  # candidate titles from path, nearest first
    folder_years: list[int] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)    # {'tvdb': '123', 'imdb': 'tt...'}
    groups: list[str] = field(default_factory=list)      # bracket tags, e.g. release group
    is_companion: bool = False
    release_group: str | None = None                     # leading [Group] tag
    anime_score: float = 0.0                             # 0..1 evidence of fansub-style naming
    trace: list[str] = field(default_factory=list)


def _clean_stem(stem: str) -> tuple[str, list[str]]:
    """Remove bracketed groups, unify separators. Returns (clean, bracket_contents)."""
    brackets = [m.group(0)[1:-1] for m in BRACKET_RE.finditer(stem)]
    s = BRACKET_RE.sub(" ", stem)
    s = re.sub(r"[()]", " ", s)                       # '(2025)' -> ' 2025 '
    s = re.sub(r"(?<=[^\W\d_])((?:19|20)\d\d)(?!\d)", r" \1", s)  # 'Nosferatu2024'
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s, brackets


def _is_stop_token(tok: str) -> bool:
    t = tok.casefold().strip("-")
    return t in RELEASE_TAGS or bool(YEAR_RE.fullmatch(tok))


def _title_from(clean: str, cut: int | None) -> str:
    """Title = tokens before `cut` (string index), stopping at the first release tag/year.
    Leading years are skipped (handles '2024.Nosferatu')."""
    prefix = clean[:cut] if cut is not None else clean
    out: list[str] = []
    leading_years: list[str] = []
    for tok in prefix.split():
        if YEAR_RE.fullmatch(tok) and not out:
            leading_years.append(tok)  # '2024.Nosferatu' -> skip; '2012.2009' -> title is '2012'
            continue
        if _is_stop_token(tok):
            break
        if tok in {"-", "–"}:
            continue
        out.append(tok)
    if not out and leading_years:
        out = [leading_years[0]]
    title = " ".join(out).strip(" -–")
    return title


def _episode_hints(clean: str) -> tuple[list[EpisodeHint], int | None]:
    """All episode marker hypotheses, and the string index of the strongest marker."""
    hints: list[EpisodeHint] = []
    first_cut: int | None = None
    claimed: list[tuple[int, int]] = []  # spans already explained by stronger patterns

    def claim(m: re.Match) -> None:
        claimed.append((m.start(), m.end()))

    def overlaps(m: re.Match) -> bool:
        return any(a < m.end() and m.start() < b for a, b in claimed)

    for m in SXXEYY_RE.finditer(clean):
        hints.append(EpisodeHint(int(m.group(1)), int(m.group(2)), 0.95, "sxxeyy"))
        claim(m)
        first_cut = m.start() if first_cut is None else min(first_cut, m.start())
    for m in NXNN_RE.finditer(clean):
        if overlaps(m):
            continue
        hints.append(EpisodeHint(int(m.group(1)), int(m.group(2)), 0.9, "nxnn"))
        claim(m)
        first_cut = m.start() if first_cut is None else min(first_cut, m.start())
    for m in EXX_RE.finditer(clean):
        if overlaps(m):
            continue
        hints.append(EpisodeHint(None, int(m.group(1)), 0.7, "exx"))
        claim(m)
        first_cut = m.start() if first_cut is None else min(first_cut, m.start())
    if not hints:
        for m in BARE_NUM_RE.finditer(clean):
            tok = m.group(1)
            if tok in RESOLUTION_NUMBERS or YEAR_RE.fullmatch(tok):
                continue
            if overlaps(m):
                continue
            # a bare number is only an episode hypothesis, weak by nature
            hints.append(EpisodeHint(None, int(tok), 0.5, "bare"))
            if first_cut is None:
                first_cut = m.start()
    return hints, first_cut


def parse_path_context(path: Path, root: Path) -> tuple[list[str], list[int], dict[str, str]]:
    """Walk ancestors from file's parent up to root: collect candidate titles, years, IDs."""
    titles: list[str] = []
    years: list[int] = []
    ids: dict[str, str] = {}
    for anc in path.parents:
        try:
            anc.relative_to(root)
        except ValueError:
            break
        name = anc.name
        if not name or anc == root:
            break
        for m in ID_RE.finditer(name):
            ids.setdefault(m.group(1).casefold(), m.group(2))
        clean, _ = _clean_stem(name)
        years.extend(find_years(clean))
        bare = ID_RE.sub(" ", clean)
        bare, _ = _clean_stem(bare)
        title = _title_from(bare, None)
        if title and not STRUCTURAL_FOLDERS.match(title):
            titles.append(title)
    return titles, years, ids


def parse_file(path: Path, root: Path) -> ParsedFile:
    stem = path.stem
    clean, brackets = _clean_stem(stem)
    pf = ParsedFile(path=path, title="", is_companion=path.suffix.casefold() in COMPANION_EXTS)

    for m in ID_RE.finditer(stem):
        pf.ids.setdefault(m.group(1).casefold(), m.group(2))
    im = IMDB_RE.search(stem)
    if im:
        pf.ids.setdefault("imdb", im.group(1))

    pf.years = find_years(clean)
    for b in brackets:                                # 'Nosferatu.[2024]' keeps its year
        for y in find_years(b):
            if y not in pf.years:
                pf.years.append(y)
    pf.episode_hints, cut = _episode_hints(clean)
    pf.title = _title_from(clean, cut)
    strong_cut = cut if any(h.source != "bare" for h in pf.episode_hints) else None
    pf.title_full = _title_from(clean, strong_cut)
    if is_year(pf.title) and len(pf.years) > 1:
        pf.years.remove(int(pf.title))     # '2012.2009': the title is 2012, the year is 2009

    # season words next to bare numbers: 'Frieren 2nd Season - 05' -> S2 E5
    if pf.episode_hints and all(h.source == "bare" for h in pf.episode_hints):
        sw = SEASON_WORD_RE.search(pf.title)
        if sw:
            season_no = int(next(g for g in sw.groups() if g))
            for h in pf.episode_hints:
                h.season = season_no
                h.confidence = 0.65
            pf.title = " ".join(SEASON_WORD_RE.sub(" ", pf.title).split()).strip(" -")

    # anime-style naming evidence
    score = 0.0
    if stem.lstrip().startswith("[") and brackets:
        pf.release_group = brackets[0].strip()
        score += 0.4 if pf.release_group.casefold() in KNOWN_ANIME_GROUPS else 0.25
    if any(CRC_RE.match(b.strip()) for b in brackets):
        score += 0.3
    if CJK_RE.search(stem) or any(CJK_RE.search(t) for t in pf.folder_titles[:1]):
        score += 0.35
    if re.search(r"(?i)\d(?:st|nd|rd|th)\s+season", clean):
        score += 0.3          # '2nd Season' is anime naming convention
    if pf.episode_hints and pf.episode_hints[0].source == "bare" and (
            pf.release_group or CJK_RE.search(stem)):
        score += 0.15
    pf.anime_score = min(1.0, score)
    pf.groups = brackets

    pf.folder_titles, pf.folder_years, folder_ids = parse_path_context(path, root)
    for k, v in folder_ids.items():
        pf.ids.setdefault(k, v)

    pf.trace.append(f"clean name: '{clean}'")
    if pf.title:
        pf.trace.append(f"file title: '{pf.title}'")
    if pf.folder_titles:
        pf.trace.append(f"folder titles: {pf.folder_titles}")
    if pf.years or pf.folder_years:
        pf.trace.append(f"years: name={pf.years} path={pf.folder_years}")
    for h in pf.episode_hints:
        pf.trace.append(f"episode hint: {h.source} s={h.season} e={h.episode} ({h.confidence})")
    if pf.ids:
        pf.trace.append(f"ids: {pf.ids}")
    if pf.anime_score:
        pf.trace.append(f"anime-style naming score: {pf.anime_score:.2f}"
                        + (f" (group '{pf.release_group}')" if pf.release_group else ""))
    return pf


def read_nfo_ids(video: Path) -> dict[str, str]:
    """Scan sibling NFO files for database IDs. Returns evidence, caller validates."""
    ids: dict[str, str] = {}
    candidates = [video.with_suffix(".nfo"), video.parent / "movie.nfo", video.parent / "tvshow.nfo"]
    for nfo in candidates:
        try:
            if not nfo.is_file():
                continue
            text = nfo.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        m = IMDB_RE.search(text)
        if m:
            ids.setdefault("imdb", m.group(1))
        for pat, key in [(r'uniqueid[^>]*type="tmdb"[^>]*>(\d+)', "tmdb"),
                         (r'uniqueid[^>]*type="tvdb"[^>]*>(\d+)', "tvdb"),
                         (r"<tmdbid>(\d+)</tmdbid>", "tmdb")]:
            mm = re.search(pat, text, re.I)
            if mm:
                ids.setdefault(key, mm.group(1))
    return ids
