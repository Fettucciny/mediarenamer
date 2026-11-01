"""Parser tests for fansub-style anime names."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediarenamer.parse import parse_file  # noqa: E402

ROOT = Path("C:/t")


def p(rel: str):
    return parse_file(ROOT / rel, ROOT)


class TestAnimeNames(unittest.TestCase):
    def test_subsplease_with_crc(self):
        f = p("[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv")
        self.assertEqual(f.title, "Sousou no Frieren")
        self.assertEqual(f.episode_hints[0].episode, 5)
        self.assertEqual(f.release_group, "SubsPlease")
        self.assertGreaterEqual(f.anime_score, 0.5)

    def test_v2_suffix(self):
        f = p("[Erai-raws] Jujutsu Kaisen - 30v2 [1080p][HEVC].mkv")
        self.assertEqual(f.episode_hints[0].episode, 30)

    def test_season_word_ordinal(self):
        f = p("Frieren 2nd Season - 05.mkv")
        self.assertEqual(f.title, "Frieren")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 5))

    def test_season_word_s2(self):
        f = p("[Nekomoe kissaten] Oshi no Ko S2 - 03 [1080p][CHS].mkv")
        self.assertEqual(f.title, "Oshi no Ko")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 3))

    def test_cjk_title(self):
        f = p("鬼灭之刃 - 05.mkv")
        self.assertEqual(f.title, "鬼灭之刃")
        self.assertEqual(f.episode_hints[0].episode, 5)
        self.assertGreater(f.anime_score, 0)

    def test_western_release_not_anime(self):
        f = p("Severance.S01E01.1080p.WEB.H264-GROUP.mkv")
        self.assertEqual(f.anime_score, 0.0)

    def test_sxxeyy_not_overridden_by_season_word(self):
        f = p("Show S2 S02E03.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 3))


if __name__ == "__main__":
    unittest.main(verbosity=1)
