"""Parser tests built from the exact filenames where FileBot failed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediarenamer.parse import normalize, parse_file  # noqa: E402

ROOT = Path("C:/t")


def p(rel: str):
    return parse_file(ROOT / rel, ROOT)


class TestEpisodeHints(unittest.TestCase):
    def test_bare_number_in_folder(self):
        f = p("Severance/01.mkv")
        self.assertEqual([h.episode for h in f.episode_hints], [1])
        self.assertEqual(f.folder_titles, ["Severance"])
        self.assertEqual(f.title, "")

    def test_name_space_number(self):
        f = p("Severance 01.mkv")
        self.assertEqual(f.title, "Severance")
        self.assertEqual(f.episode_hints[0].episode, 1)

    def test_name_dash_number(self):
        f = p("Severance - 01.mkv")
        self.assertEqual(f.title, "Severance")
        self.assertEqual(f.episode_hints[0].episode, 1)

    def test_year_then_number(self):
        f = p("Shogun.2024.01.1080p.mkv")
        self.assertEqual(f.title, "Shogun")
        self.assertIn(2024, f.years)
        self.assertEqual(f.episode_hints[0].episode, 1)

    def test_sxxeyy(self):
        f = p("Severance.S01E02.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode, h.source), (1, 2, "sxxeyy"))

    def test_nxnn(self):
        f = p("Severance.1x02.mkv")
        h = f.episode_hints[0]
        self.assertEqual((h.season, h.episode), (1, 2))

    def test_fansub_brackets(self):
        f = p("[Skymoon-Raws] Hyakkano - 01 [ViuTV][WEB-DL][1080p][AVC AAC].mkv")
        self.assertEqual(f.title, "Hyakkano")
        self.assertEqual(f.episode_hints[0].episode, 1)

    def test_resolution_not_episode(self):
        f = p("Show.Name.S01E05.1080p.mkv")
        self.assertEqual(len(f.episode_hints), 1)
        self.assertEqual(f.episode_hints[0].episode, 5)


class TestYears(unittest.TestCase):
    def test_year_after_title(self):
        f = p("Nosferatu.2024.1080p.mkv")
        self.assertEqual(f.title, "Nosferatu")
        self.assertEqual(f.years, [2024])

    def test_year_first(self):
        f = p("2024.Nosferatu.1080p.mkv")
        self.assertEqual(f.title, "Nosferatu")
        self.assertIn(2024, f.years)

    def test_year_at_end(self):
        f = p("Nosferatu.1080p.2024.BluRay.mkv")
        self.assertEqual(f.title, "Nosferatu")
        self.assertIn(2024, f.years)

    def test_two_years(self):
        f = p("Nosferatu.1922.2024.Remaster.1080p.mkv")
        self.assertEqual(f.years, [1922, 2024])

    def test_year_as_title(self):
        f = p("1917.2019.1080p.mkv")
        self.assertEqual(f.title, "1917")
        self.assertIn(2019, f.years)

    def test_hyphenated_title(self):
        f = p("The.Three-Body.Problem.2015.1080p.mkv")
        self.assertEqual(normalize(f.title), "the three body problem")
        self.assertEqual(f.years, [2015])

    def test_year_in_folder(self):
        f = p("Dune (2021)/Dune.1080p.BluRay.mkv")
        self.assertEqual(f.title, "Dune")
        self.assertIn(2021, f.folder_years)


class TestPathContext(unittest.TestCase):
    def test_structural_folder_ignored(self):
        f = p("Downloads/Season 1/01.mkv")
        self.assertEqual(f.folder_titles, [])

    def test_id_tag(self):
        f = p("Journey to the West {tvdb-13923}/E01.1986.mkv")
        self.assertEqual(f.ids.get("tvdb"), "13923")
        self.assertEqual(f.folder_titles, ["Journey to the West"])
        self.assertIn(1986, f.years)


if __name__ == "__main__":
    unittest.main(verbosity=2)
