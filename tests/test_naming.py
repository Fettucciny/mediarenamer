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
    def test_tv_folder_has_id_but_no_year(self):
        r = episode("x.mkv", "Severance", 2022, 1, 1, None, {"tvmaze": 44201, "tvdb": 371980})
        self.assertEqual(plan.folder_name(r), "Severance {tvdb-371980}")

    def test_cross_provider_ids_are_one_title(self):
        # season folders inside one show folder: S1 matched by TVmaze, S2 by
        # TMDb -- disjoint primary ids, shared tvdb, one show
        a = episode("Show/Season 1/a.S01E01.mkv", "Severance", 2022, 1, 1, None,
                    {"tvmaze": 44933, "tvdb": 371980})
        b = episode("Show/Season 2/01.mkv", "Severance", 2022, 2, 1, None,
                    {"tmdb": 95396, "tvdb": 371980})
        groups = plan.title_groups([a, b])
        self.assertEqual(groups[id(a)], groups[id(b)])
        self.assertTrue(plan.planned_folder_name([a, b], ROOT / "Show")
                        .startswith("Severance {"))

    def test_same_name_and_year_merge_without_shared_ids(self):
        a = episode("Show/Season 1/a.S01E01.mkv", "Severance", 2022, 1, 1, None, {"tvmaze": 44933})
        b = episode("Show/Season 2/01.mkv", "Severance", 2022, 2, 1, None, {"tmdb": 95396})
        groups = plan.title_groups([a, b])
        self.assertEqual(groups[id(a)], groups[id(b)])

    def test_same_name_different_year_stay_separate(self):
        a = episode("x/a.S01E01.mkv", "Shameless", 2004, 1, 1, None, {})
        b = episode("x/b.S01E01.mkv", "Shameless", 2011, 1, 1, None, {})
        groups = plan.title_groups([a, b])
        self.assertNotEqual(groups[id(a)], groups[id(b)])

    def test_folder_requires_single_title(self):
        a = episode("Show/a.S01E01.mkv", "Severance", 2022, 1, 1, None, {"tvdb": 1})
        b = episode("Show/b.S01E01.mkv", "Shogun", 2024, 1, 1, None, {"tvdb": 2})
        self.assertIsNone(plan.planned_folder_name([a, b], ROOT / "Show"))
        self.assertEqual(plan.planned_folder_name([a], ROOT / "Show"), "Severance {tvdb-1}")


class TestMovieFoldering(unittest.TestCase):
    """Every movie ends in a folder named like its video file."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="mr_plan_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _movie_at(self, rel: str, title: str, year: int, tmdb_id: int):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        r = MatchResult(file=parse_file(p, self.tmp), kind="movie", confidence=0.9)
        r.movie_title, r.movie_year, r.tmdb_id = title, year, tmdb_id
        plan._director_cache[tmdb_id] = None
        return r

    def test_loose_movie_gets_its_own_subfolder(self):
        a = self._movie_at("drop/Heat.1995.mkv", "Heat", 1995, 949)
        b = self._movie_at("drop/Alien.1979.mkv", "Alien", 1979, 348)
        ops = build_ops = plan.build_plan([a, b], rename_roots=[self.tmp / "drop"])
        by_src = {o.src.name: o for o in build_ops if o.result is not None}
        self.assertEqual(by_src["Heat.1995.mkv"].dst.parent.name, "Heat (1995)")
        self.assertEqual(by_src["Alien.1979.mkv"].dst.parent.name, "Alien (1979)")
        self.assertFalse([o for o in ops if o.result is None], "no folder renames expected")
        self.assertEqual(a.new_name, "Heat (1995)\\Heat (1995).mkv")

    def test_movie_in_own_folder_renames_the_folder(self):
        a = self._movie_at("drop/Heat 1995 BluRay/Heat.1995.1080p.x265-GRP.mkv", "Heat", 1995, 949)
        ops = plan.build_plan([a], rename_roots=[self.tmp / "drop"])
        folder_ops = [o for o in ops if o.result is None]
        self.assertEqual(len(folder_ops), 1)
        self.assertEqual(folder_ops[0].src, self.tmp / "drop" / "Heat 1995 BluRay")
        self.assertEqual(folder_ops[0].dst.name, "Heat (1995) 1080p.x265-GRP")
        # the file is renamed in place; the folder op then renames its folder
        self.assertEqual(a.new_name, "Heat (1995) 1080p.x265-GRP.mkv")
        self.assertEqual(plan.planned_folder_name([a], self.tmp / "drop" / "Heat 1995 BluRay"),
                         "Heat (1995) 1080p.x265-GRP")

    def test_structural_parent_is_never_renamed(self):
        a = self._movie_at("Movies/Heat.1995.mkv", "Heat", 1995, 949)
        ops = plan.build_plan([a], rename_roots=[self.tmp / "Movies"])
        self.assertFalse([o for o in ops if o.result is None])
        self.assertEqual(ops[0].dst.parent.name, "Heat (1995)")

    def test_shared_folder_on_disk_blocks_rename(self):
        a = self._movie_at("drop/Heat.1995.mkv", "Heat", 1995, 949)
        (self.tmp / "drop" / "unrelated.mkv").write_bytes(b"")
        ops = plan.build_plan([a], rename_roots=[self.tmp / "drop"])
        self.assertFalse([o for o in ops if o.result is None])
        self.assertEqual(ops[0].dst.parent.name, "Heat (1995)")


if __name__ == "__main__":
    unittest.main(verbosity=1)
