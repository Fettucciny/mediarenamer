"""End-to-end GUI test on the offscreen Qt platform.

Drops two show folders at once -> two columns; applies one column -> its files
are renamed in place, its folder is renamed to the Plex form, the column
retires; undo restores both. Needs network (TVmaze). Skips without PySide6.
Set MR_SHOTS=<dir> to also save screenshots."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from mediarenamer.gui.app import MainWindow
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def wait_for(cond, timeout_ms=180_000) -> bool:
    loop = QEventLoop()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll = QTimer()
    poll.setInterval(100)

    def check():
        if cond():
            loop.quit()
    poll.timeout.connect(check)
    deadline.start(timeout_ms)
    poll.start()
    loop.exec()
    return cond()


CFG = {"recursive": True, "output_dir": "", "prefer_original_titles": False, "recent_paths": [],
       "tmdb_api_key": "", "tv_scheme": "plex", "movie_scheme": "filebot", "rename_folders": True}


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = Path(tempfile.mkdtemp(prefix="mr_gui_"))
        cls.sev = cls.tmp / "Severance"
        cls.sev.mkdir()
        cls.sev_names = ["Severance.S01E01.1080p.WEB.H264-NTb.mkv", "Severance.S01E02.1080p.WEB.H264-NTb.mkv",
                         "Severance.S01E02.eng.srt"]
        for n in cls.sev_names:
            (cls.sev / n).write_bytes(b"")
        cls.sho = cls.tmp / "Shogun.2024.S01.1080p"
        cls.sho.mkdir()
        for n in ["Shogun.2024.S01E01.1080p.mkv", "Shogun.2024.S01E02.1080p.mkv"]:
            (cls.sho / n).write_bytes(b"")
        cls.shots = Path(os.environ["MR_SHOTS"]) if os.environ.get("MR_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def shot(self, win, name):
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.app.processEvents()
            win.grab().save(str(self.shots / f"{name}.png"))

    def test_two_columns_apply_folder_rename_undo(self):
        win = MainWindow(dict(CFG))
        win.confirm_apply = False
        win.animate = False
        win.resize(1280, 760)
        win.show()
        self.shot(win, "01_empty")

        win.add_paths([self.sev, self.sho])
        self.assertTrue(wait_for(lambda: bool(win.visible_panels)), "matching did not finish")
        self.app.processEvents()
        self.shot(win, "02_two_columns")

        panels = win.visible_panels
        self.assertEqual(len(panels), 2, [p.section.title for p in panels])
        sev = next(p for p in panels if p.section.title.startswith("Severance"))
        sho = next(p for p in panels if "Sh" in p.section.title and p is not sev)
        self.assertEqual(len(sev.model.rows), 3)
        self.assertEqual(len(sho.model.rows), 2)
        self.assertTrue(all(r.status == "AUTO" for r in sev.model.rows),
                        [(r.file.path.name, r.status, r.trace[-1]) for r in sev.model.rows])
        # Plex file form and the FileBot-style folder form
        self.assertTrue(all(r.new_name.startswith("Severance (2022) - S01E0") for r in sev.model.rows),
                        [r.new_name for r in sev.model.rows])
        self.assertTrue(sev.section.folder_new_name and sev.section.folder_new_name.startswith("Severance {"),
                        sev.section.folder_new_name)

        sev.table.selectRow(0)
        self.app.processEvents()
        self.assertIn("match:", win.trace.toPlainText())
        self.shot(win, "03_trace")

        win.apply_panel(sev)
        self.app.processEvents()
        new_folder = next(p for p in self.tmp.iterdir() if p.name.startswith("Severance {"))
        renamed = sorted(p.name for p in new_folder.iterdir())
        self.assertTrue(all(n.startswith("Severance (2022) - S01E0") for n in renamed), renamed)
        self.assertNotIn(sev, win.visible_panels, "finished column should retire")
        self.assertEqual(len(win.visible_panels), 1)
        self.shot(win, "04_after_apply")

        win.undo()
        self.assertTrue(wait_for(lambda: not (win.worker and win.worker.isRunning()), 60_000))
        self.assertTrue(self.sev.is_dir(), list(self.tmp.iterdir()))
        self.assertEqual(sorted(p.name for p in self.sev.iterdir()), sorted(self.sev_names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
