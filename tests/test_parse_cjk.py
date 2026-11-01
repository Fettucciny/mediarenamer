"""Parser tests for Chinese, Japanese and Korean naming conventions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediarenamer.parse import cjk_int, parse_file  # noqa: E402

ROOT = Path("C:/t")


def p(rel: str):
    return parse_file(ROOT / rel, ROOT)


class TestChinese(unittest.TestCase):
    def test_di_ji_marker(self):
        f = p("庆余年/第01集.mkv")
        self.assertEqual(f.episode_hints[0].episode, 1)
        self.assertEqual(f.episode_hints[0].source, "cjk")
        self.assertEqual(f.folder_titles, ["庆余年"])

    def test_season_and_episode_words(self):
        f = p("庆余年 第2季 第03集 1080P.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 3))
        self.assertEqual(f.title, "庆余年")

    def test_chinese_numeral_season(self):
        f = p("庆余年 第二季 第十二集.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 12))

    def test_site_watermark_and_tags(self):
        f = p("[阳光电影www.ygdy8.com].狂飙.The.Knockout.2023.EP01.HD1080P.国语中字.mkv")
        self.assertIsNone(f.release_group)
        self.assertEqual(f.title, "狂飙 The Knockout")
        self.assertEqual(f.episode_hints[0].episode, 1)
        self.assertIn(2023, f.years)
        self.assertLess(f.anime_score, 0.5)

    def test_fullwidth_brackets(self):
        f = p("【高清影视之家发布 www.HDBTHD.com】流浪地球2[国语配音+中文字幕].The.Wandering.Earth.II.2023.2160p.mkv")
        self.assertIsNone(f.release_group)
        self.assertEqual(f.title_full, "流浪地球2 The Wandering Earth II")
        self.assertEqual(f.years, [2023])

    def test_glued_tags(self):
        f = p("让子弹飞.2010.BluRay.1080p.国语中字.mkv")
        self.assertEqual(f.title, "让子弹飞")
        self.assertEqual(f.years, [2010])

    def test_season_folder_gives_season(self):
        f = p("庆余年/第2季/第05集.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 5))
        self.assertEqual(f.folder_titles, ["庆余年"])

    def test_cjk_int(self):
        self.assertEqual(cjk_int("十"), 10)
        self.assertEqual(cjk_int("二十一"), 21)
        self.assertEqual(cjk_int("一百零三"), 103)
        self.assertEqual(cjk_int("07"), 7)


class TestKorean(unittest.TestCase):
    def test_hwa(self):
        f = p("더 글로리 1화.mkv")
        self.assertEqual(f.title, "더 글로리")
        self.assertEqual(f.episode_hints[0].episode, 1)

    def test_broadcast_date_not_episode(self):
        f = p("더 글로리.E01.221230.1080p.mkv")
        self.assertEqual(f.title, "더 글로리")
        self.assertEqual([h.episode for h in f.episode_hints], [1])

    def test_sijeun(self):
        f = p("오징어 게임 시즌2 3화.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (2, 3))
        self.assertEqual(f.title, "오징어 게임")

    def test_not_anime(self):
        f = p("오징어 게임.Squid.Game.S01E01.1080p.NF.WEB-DL.mkv")
        self.assertLess(f.anime_score, 0.5)
        self.assertEqual(f.title, "오징어 게임 Squid Game")


class TestJapanese(unittest.TestCase):
    def test_dai_wa(self):
        f = p("半沢直樹 第1話.mkv")
        self.assertEqual(f.title, "半沢直樹")
        self.assertEqual(f.episode_hints[0].episode, 1)

    def test_hash_number(self):
        f = p("VIVANT #01.mkv")
        self.assertEqual(f.title, "VIVANT")
        self.assertEqual(f.episode_hints[0].source, "cjk")

    def test_season_ki(self):
        f = p("孤独のグルメ Season10 第01話.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (10, 1))
        self.assertEqual(f.title, "孤独のグルメ")

    def test_movie_with_japanese_punct(self):
        f = p("君の名は。.Your.Name.2016.1080p.mkv")
        self.assertEqual(f.title, "君の名は Your Name")
        self.assertEqual(f.years, [2016])


if __name__ == "__main__":
    unittest.main(verbosity=1)
