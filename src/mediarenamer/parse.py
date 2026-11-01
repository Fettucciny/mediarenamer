"""Filename and path parsing: extract title, years, episode hypotheses, IDs.

Everything extracted is *evidence* with a confidence, never a verdict.
Handles western release names, fansub names, and Chinese / Japanese /
Korean conventions (第01集, 第2季, 1화, 시즌2, 第1話, #01, 【site】 tags).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
              ".webm", ".mpg", ".mpeg", ".m4v", ".rmvb", ".rm"}
COMPANION_EXTS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}

# Words that are release metadata, never part of a title once seen.
RELEASE_TAGS = {
    "480p", "576p", "720p", "1080p", "2160p", "4320p", "4k", "8k", "uhd", "hd", "fhd", "bd",
    "bluray", "blu", "ray", "bdrip", "brrip", "remux", "webrip", "web", "dl",
    "webdl", "hdtv", "dvdrip", "dvd", "hdrip", "cam", "ts", "tvrip", "iptv",
    "x264", "x265", "h264", "h265", "avc", "hevc", "av1", "xvid", "divx",
    "10bit", "8bit", "hdr", "hdr10", "dovi", "dv", "sdr",
    "aac", "ac3", "eac3", "dts", "truehd", "atmos", "flac", "mp3", "opus",
    "dd5", "ddp5", "5.1", "7.1", "2.0",
    "repack", "proper", "rerip", "internal", "limited", "extended", "uncut",
    "unrated", "remastered", "remaster", "imax", "complete", "multi", "dual",
    "subbed", "dubbed", "sub", "subs", "nf", "amzn", "dsnp", "hulu", "atvp",
    "max", "viutv", "gb", "cht", "chs", "big5", "korean", "japanese", "chinese",
    "mandarin", "cantonese", "kor", "jpn", "chi",
}
STOP_RE = re.compile(
    r"(?i)^(?:(?:hd|bd|fhd|uhd|web)?(?:480|576|720|1080|2160|4320)[pi]?|[hx]\.?26[45]|"
    r"aac\d*|ddp?\d(?:\.\d)?|\d+fps|\d+bit|hdr\d*|\d(?:\.\d)?ch|web-dl|blu-ray)$")
RESOLUTION_NUMBERS = {"480", "576", "720", "1080", "2160", "4320"}

# CJK release words glued to other text ('1080P国语中字'): stripped as substrings.
CJK_TAGS_RE = re.compile(
    r"国粤双语|国英双语|中英双字|中英字幕|中文字幕|国语配音|国语中字|粤语中字|简繁字幕|简繁内封|"
    r"中字|国语|粤语|国配|配音|简繁|简体|繁体|内封|内嵌|外挂|字幕|双语|高清|超清|蓝光|原盘|"
    r"修复版|高码|完结|全集|更新至\d*|全\d+[集话話]|无水印|无删减|未删减|加长版|导演剪辑版|"
    r"日语|韩语|英语|泰语|台配|港版|台版|网络版|电视版|"
    r"자막|더빙|한글|완결|무삭제|우리말|"
    r"吹替版|字幕版|吹替|日本語|無修正|高画質")

# Folder names that are structure, never titles.
STRUCTURAL_FOLDERS = re.compile(
    r"(?i)^(season[ ._-]?\d+|s\d{1,2}|specials?|extras?|featurettes?|samples?|"
    r"subs?|subtitles?|downloads?|torrents?|complete|collection|videos?|movies?|"
    r"films?|tv|series|anime|media|new folder|temp|tmp|incoming|unsorted|misc|other|"
    r"字幕|bdmv|video_ts|电影|电视剧|动漫|动画|下载|新建文件夹|剧集|综艺|纪录片|"
    r"国产剧|日剧|韩剧|美剧|英剧|港剧|台剧|泰剧|"
    r"영화|드라마|다운로드|애니|映画|ドラマ|アニメ|ダウンロード)$")

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
# 第01集 / 第1話 / 第3回 / 1화 / 제1화 / 12회 / #01
CJK_EP_RE = re.compile(
    r"第\s*(\d{1,4}|[零一二三四五六七八九十百]+)\s*[集話话回]"
    r"|(?<![\d\w])(\d{1,3})\s*[話话화회](?![\d])"
    r"|제\s*(\d{1,3})\s*화"
    r"|(?<![\w#])#(\d{1,3})(?![\d])")
BARE_NUM_RE = re.compile(r"(?<![\w(])(\d{1,3})(?:v\d)?(?![\w)])")
BRACKET_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}|【[^】]*】")
SITE_TAG_RE = re.compile(r"(?i)www\.|\.(?:com|net|org|cc|tv|me|xyz|top|vip|la|cn|in)(?![a-z])|发布|压制组?$")
ID_RE = re.compile(r"(?i)\{?(tmdb|tvdb|imdb|anilist|mal)[-=:]((?:tt)?\d+)\}?")
IMDB_RE = re.compile(r"(?i)(?<![a-z0-9])(tt\d{7,8})(?![0-9])")
CRC_RE = re.compile(r"^[A-Fa-f0-9]{8}$")
KANA_RE = re.compile(r"[぀-ヿ]")
HAN_RE = re.compile(r"[㐀-䶿一-鿿]")
HANGUL_RE = re.compile(r"[가-힯]")
CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
CJK_PUNCT_RE = re.compile(r"[。、，！？：；「」『』《》〈〉・･~～]")
# 'Frieren 2nd Season - 05', 'Show Season 2 - 05', 'Show S2 - 05', 第2季, 시즌2, 2期, シーズン2
SEASON_WORD_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?:(\d{1,2})(?:st|nd|rd|th)[ ]+season|season[ ]*(\d{1,2})|s(\d{1,2}))(?![a-z0-9])"
    r"|第\s*(\d{1,2}|[一二三四五六七八九十]+)\s*季|시즌\s*(\d{1,2})|シーズン\s*(\d{1,2})"
    r"|(?<![\d\w])(\d{1,2})\s*期(?![間])")
KNOWN_ANIME_GROUPS = {
    "subsplease", "erai-raws", "horriblesubs", "judas", "ember", "asw", "skymoon-raws",
    "nekomoe kissaten", "lolihouse", "ani", "sakurato", "lilith-raws", "nc-raws", "vcb-studio",
    "commie", "kametsu", "yameii", "tsundere-raws", "ohys-raws", "moozzi2", "beatrice-raws",
    "anime time", "reinforce", "gjm", "doki", "coalgirls", "underwater", "fff", "vivid",
    "damedesuyo", "sallysubs", "exiled-destiny", "utw", "chihiro", "comicat", "romanticat",
    "sweetsub", "kamigami", "dmhy", "mingy", "haruhana", "sbsub", "billion meta lab",
    "nan-raws", "hysub", "ktxp", "jibaketa", "orion", "seed-raws", "trix", "varyg", "toonshub",
}

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
              "八": 8, "九": 9}


def cjk_int(s: str) -> int | None:
    """'12' -> 12, '三' -> 3, '十' -> 10, '二十一' -> 21, '一百零三' -> 103."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            cur = _CN_DIGITS[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        else:
            return None
    return total + cur


def normalize(s: str) -> str:
    """Casefold, strip diacritics and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.casefold())
    return " ".join(s.split())


def has_cjk(s: str) -> bool:
    return bool(CJK_RE.search(s))


@dataclass
class EpisodeHint:
    season: int | None      # None = unknown season
    episode: int
    confidence: float       # how certain this token is an episode marker
    source: str             # 'sxxeyy' | 'nxnn' | 'exx' | 'cjk' | 'bare'


@dataclass
class ParsedFile:
    path: Path
    title: str                                 # title before the first episode marker ('' if none)
    title_full: str = ""                       # title ignoring bare numbers (movie view: 'Ne Zha 2')
    years: list[int] = field(default_factory=list)       # all plausible years, name first then path
    episode_hints: list[EpisodeHint] = field(default_factory=list)
    folder_titles: list[str] = field(default_factory=list)  # candidate titles from path, nearest first
    folder_years: list[int] = field(default_factory=list)
    folder_season: int | None = None                     # from a 'Season 2' / '第2季' folder
    ids: dict[str, str] = field(default_factory=dict)    # {'tvdb': '123', 'imdb': 'tt...'}
    groups: list[str] = field(default_factory=list)      # bracket tags, e.g. release group
    is_companion: bool = False
    release_group: str | None = None                     # leading [Group] tag (not site watermarks)
    anime_score: float = 0.0                             # 0..1 evidence of fansub-style naming
    trace: list[str] = field(default_factory=list)


def _clean_stem(stem: str) -> tuple[str, list[str]]:
    """Normalize width, remove bracketed groups, strip CJK release words, unify
    separators. Returns (clean, bracket_contents)."""
    s = unicodedata.normalize("NFKC", stem)           # full-width 'ＥＰ０１（２０１９）' -> ASCII
    brackets = [m.group(0)[1:-1] for m in BRACKET_RE.finditer(s)]
    s = BRACKET_RE.sub(" ", s)
    s = re.sub(r"[()]", " ", s)                       # '(2025)' -> ' 2025 '
    s = CJK_TAGS_RE.sub(" ", s)                       # '1080P国语中字' -> '1080P'
    s = CJK_PUNCT_RE.sub(" ", s)
    s = re.sub(r"(?<=[^\W\d_])((?:19|20)\d\d)(?!\d)", r" \1", s)  # 'Nosferatu2024'
    s = re.sub(r"(?<=\d)年", " ", s)                  # '2023年' -> '2023'
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s, brackets


def _is_stop_token(tok: str) -> bool:
    t = tok.casefold().strip("-")
    return t in RELEASE_TAGS or bool(STOP_RE.match(t)) or is_year(tok)


def _title_from(clean: str, cut: int | None) -> str:
    """Title = tokens before `cut` (string index), stopping at the first release tag/year.
    Leading years are skipped (handles '2024.Nosferatu')."""
    prefix = clean[:cut] if cut is not None else clean
    out: list[str] = []
    leading_years: list[str] = []
    for tok in prefix.split():
        if is_year(tok) and not out:
            leading_years.append(tok)  # '2024.Nosferatu' -> skip; '2012.2009' -> title is '2012'
            continue
        if _is_stop_token(tok):
            break
        if tok in {"-", "–"}:
            continue
        out.append(tok)
    if not out and leading_years:
        out = [leading_years[0]]
    return " ".join(out).strip(" -–")


def _episode_hints(clean: str) -> tuple[list[EpisodeHint], int | None]:
    """All episode marker hypotheses, and the string index of the strongest marker."""
    hints: list[EpisodeHint] = []
    first_cut: int | None = None
    claimed: list[tuple[int, int]] = []  # spans already explained by stronger patterns

    def claim(m: re.Match) -> None:
        claimed.append((m.start(), m.end()))

    def overlaps(m: re.Match) -> bool:
        return any(a < m.end() and m.start() < b for a, b in claimed)

    def cut_at(m: re.Match) -> None:
        nonlocal first_cut
        first_cut = m.start() if first_cut is None else min(first_cut, m.start())

    for m in SXXEYY_RE.finditer(clean):
        hints.append(EpisodeHint(int(m.group(1)), int(m.group(2)), 0.95, "sxxeyy"))
        claim(m)
        cut_at(m)
    for m in NXNN_RE.finditer(clean):
        if overlaps(m):
            continue
        hints.append(EpisodeHint(int(m.group(1)), int(m.group(2)), 0.9, "nxnn"))
        claim(m)
        cut_at(m)
    for m in EXX_RE.finditer(clean):
        if overlaps(m):
            continue
        hints.append(EpisodeHint(None, int(m.group(1)), 0.7, "exx"))
        claim(m)
        cut_at(m)
    for m in CJK_EP_RE.finditer(clean):
        if overlaps(m):
            continue
        n = cjk_int(next(g for g in m.groups() if g))
        if n is None:
            continue
        hints.append(EpisodeHint(None, n, 0.75, "cjk"))
        claim(m)
        cut_at(m)
    if not hints:
        for m in BARE_NUM_RE.finditer(clean):
            tok = m.group(1)
            if tok in RESOLUTION_NUMBERS or is_year(tok):
                continue
            if overlaps(m):
                continue
            # a bare number is only an episode hypothesis, weak by nature
            hints.append(EpisodeHint(None, int(tok), 0.5, "bare"))
            if first_cut is None:
                first_cut = m.start()
    return hints, first_cut


def _season_from(text: str) -> int | None:
    m = SEASON_WORD_RE.search(text)
    if not m:
        return None
    return cjk_int(next(g for g in m.groups() if g))


def parse_path_context(path: Path, root: Path) -> tuple[list[str], list[int], dict[str, str], int | None]:
    """Walk ancestors from file's parent up to root: candidate titles, years, IDs,
    and a season number from the nearest 'Season N' / '第N季' folder."""
    titles: list[str] = []
    years: list[int] = []
    ids: dict[str, str] = {}
    folder_season: int | None = None
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
        if folder_season is None and re.fullmatch(
                r"(?i)\s*(?:season\s*\d{1,2}|s\d{1,2}|第\s*[\d一二三四五六七八九十]+\s*季|"
                r"시즌\s*\d{1,2}|シーズン\s*\d{1,2}|\d{1,2}\s*期)\s*", bare):
            folder_season = _season_from(bare)
            continue   # a season folder is structure, not a title
        title = _title_from(bare, None)
        if title and not STRUCTURAL_FOLDERS.match(title):
            titles.append(title)
    return titles, years, ids, folder_season


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

    pf.folder_titles, pf.folder_years, folder_ids, pf.folder_season = parse_path_context(path, root)
    for k, v in folder_ids.items():
        pf.ids.setdefault(k, v)

    # season words next to season-less markers: 'Frieren 2nd Season - 05', '庆余年 第2季 第01集'
    if pf.episode_hints and all(h.season is None for h in pf.episode_hints):
        season_no = _season_from(pf.title) or _season_from(clean[:cut] if cut else "")
        src = "name"
        if season_no is None and pf.folder_season is not None:
            season_no, src = pf.folder_season, "folder"
        if season_no is None:
            # Chinese sequel convention: '庆余年2' / '欢乐颂3' means season 2 / 3
            m = re.search(r"([㐀-䶿一-鿿])([2-9])(?=\s|$)", pf.title)
            if m:
                season_no, src = int(m.group(2)), "sequel-digit"
                pf.title = (pf.title[:m.start(2)] + pf.title[m.end(2):]).strip()
        if season_no is not None:
            for h in pf.episode_hints:
                h.season = season_no
                h.confidence = max(h.confidence, 0.65)
            if src == "name":
                pf.title = " ".join(SEASON_WORD_RE.sub(" ", pf.title).split()).strip(" -")
    pf.title_full = " ".join(SEASON_WORD_RE.sub(" ", pf.title_full).split()).strip(" -") or pf.title_full

    # anime-style naming evidence (kana and fansub groups count; Han/Hangul alone do not:
    # Chinese and Korean dramas share those scripts)
    score = 0.0
    lead = unicodedata.normalize("NFKC", stem).lstrip()
    if lead[:1] in "[【" and brackets and not SITE_TAG_RE.search(brackets[0]):
        pf.release_group = brackets[0].strip()
        score += 0.4 if pf.release_group.casefold() in KNOWN_ANIME_GROUPS else 0.25
    if any(CRC_RE.match(b.strip()) for b in brackets):
        score += 0.3
    if KANA_RE.search(stem) or any(KANA_RE.search(t) for t in pf.folder_titles[:1]):
        score += 0.25
    elif HAN_RE.search(stem) or any(HAN_RE.search(t) for t in pf.folder_titles[:1]):
        score += 0.1
    if re.search(r"(?i)\d(?:st|nd|rd|th)\s+season", clean):
        score += 0.3          # '2nd Season' is anime naming convention
    if pf.episode_hints and pf.episode_hints[0].source == "bare" and pf.release_group:
        score += 0.15
    pf.anime_score = min(1.0, score)
    pf.groups = brackets
    if pf.release_group is None:
        # scene style: '...x264-WiKi', '...WEB-DL-NTb' -> trailing group after the last '-'
        tail = BRACKET_RE.sub("", unicodedata.normalize("NFKC", stem)).strip()
        if pf.is_companion:
            tail = re.sub(r"\.[A-Za-z-]{2,7}$", "", tail)   # 'x264-WiKi.chs' -> 'x264-WiKi'
        m = re.search(r"-([A-Za-z][A-Za-z0-9]{1,15})$", tail)
        if m and m.group(1).casefold() not in RELEASE_TAGS and not STOP_RE.match(m.group(1)):
            pf.release_group = m.group(1)

    pf.trace.append(f"clean name: '{clean}'")
    if pf.title:
        pf.trace.append(f"file title: '{pf.title}'")
    if pf.folder_titles:
        pf.trace.append(f"folder titles: {pf.folder_titles}")
    if pf.folder_season is not None:
        pf.trace.append(f"season folder: {pf.folder_season}")
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
