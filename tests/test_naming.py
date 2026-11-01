"""Naming-scheme tests: FileBot-style movie names, Plex TV names, folder names.
No network: director lookup is stubbed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediarenamer import plan  # noqa: E402
from mediarenamer.match import MatchResult  # noqa: E402
from mediarenamer.parse import parse_file  # noqa: E402

ROOT = Path("C:/t")


def movie(name: str, title: str, year: int, tmdb_id: int = 1, director=None, original=None):
    r = MatchResult(file=parse_file(ROOT / name, ROOT), kind="movie", confidence=0.9)
    r.movie_title, r.movie_year, r.tmdb_id, r.movie_original = title, year, tmdb_id, original
    plan._director_cache[tmdb_id] = director
    return r


def episode(name: str, show: str, year: int, s: int, e: int, title: str | None, ids: dict):
    r = MatchResult(file=parse_file(ROOT / name, ROOT), kind="tv", confidence=0.9)
    r.show, r.show_year, r.season, r.episode, r.episode_title, r.show_ids = show, year, s, e, title, ids
    return r


class TestMovieFileBotScheme(unittest.TestCase):
    def test_full_form(self):
        r = movie("Dune.Part.Two.2024.1080p.BluRay.x265-GROUP.mkv", "Dune: Part Two", 2024, 693134,
                  director="Denis Villeneuve")
        self.assertEqual(plan.movie_stem(r, "filebot", False),
                         "Dune.Part.Two (2024) [Denis Villeneuve] 1080p.x265-GROUP")

    def test_missing_director_and_group(self):
        r = movie("Nosferatu.2024.2160p.WEB-DL.mkv", "Nosferatu", 2024, 426063)
        self.assertEqual(plan.movie_stem(r, "filebot", False), "Nosferatu (2024) 2160p")

    def test_subtitle_language_suffix(self):
        r = movie("Dune.2021.1080p.x264-WiKi.chs.srt", "Dune", 2021, 438631, director="Denis Villeneuve")
        self.assertEqual(plan.movie_stem(r, "filebot", False),
                         "Dune (2021).chs [Denis Villeneuve] 1080p.x264-WiKi")

    def test_upper_initial_keeps_inner_case(self):
        r = movie("x.mkv", "the lord of the RINGS", 2001, 5)
        self.assertEqual(plan.dotted("the lord of the RINGS"), "The.Lord.Of.The.RINGS")

    def test_original_title_preference(self):
        r = movie("寄生虫.Parasite.2019.1080p.mkv", "Parasite", 2019, 496243, original="기생충")
        self.assertEqual(plan.movie_stem(r, "filebot", True), "기생충 (2019) 1080p")

    def test_simple_scheme(self):
        r = movie("Dune.2021.mkv", "Dune", 2021, 438631)
        self.assertEqual(plan.movie_stem(r, "simple", False), "Dune (2021)")


class TestTvPlexScheme(unittest.TestCase):
    def test_plex_file_part(self):
        r = episode("Severance.S01E01.mkv", "Severance", 2022, 1, 1, "Good News About Hell", {"tvdb": 371980})
        self.assertEqual(plan.tv_stem(r, "plex", False), "Severance (2022) - S01E01 - Good News About Hell")

    def test_plex_without_episode_title(self):
        r = episode("x.mkv", "The Glory", 2022, 1, 3, None, {"tmdb": 135157})
        self.assertEqual(plan.tv_stem(r, "plex", False), "The Glory (2022) - S01E03")

    def test_colon_in_title(self):
        r = episode("x.mkv", "Frieren: Beyond Journey's End", 2023, 1, 5, "Killing Magic", {"anilist": 154587})
        self.assertEqual(plan.tv_stem(r, "plex", False),
                         "Frieren - Beyond Journey's End (2023) - S01E05 - Killing Magic")


class TestFolderName(unittest.TestCase):
    def test_tv_folder_prefers_tmdb_then_tvdb(self):
        r = episode("x.mkv", "Severance", 2022, 1, 1, None, {"tvmaze": 44201, "tvdb": 371980})
        self.assertEqual(plan.folder_name(r), "Severance (2022) {tvdb-371980}")

    def test_movie_folder(self):
        r = movie("x.mkv", "Dune: Part Two", 2024, 693134)
        self.assertEqual(plan.folder_name(r), "Dune - Part Two (2024) {tmdb-693134}")

    def test_folder_requires_single_title(self):
        a = episode("Show/a.S01E01.mkv", "Severance", 2022, 1, 1, None, {"tvdb": 1})
        b = episode("Show/b.S01E01.mkv", "Shogun", 2024, 1, 1, None, {"tvdb": 2})
        self.assertIsNone(plan.planned_folder_name([a, b], ROOT / "Show"))
        self.assertEqual(plan.planned_folder_name([a], ROOT / "Show"), "Severance (2022) {tvdb-1}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
