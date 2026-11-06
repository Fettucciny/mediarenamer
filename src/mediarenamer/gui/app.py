"""mediarenamer desktop app.

Drop folders or files. Each title (one show, one movie) gets its own column
with its own review list and Apply button. Up to four columns are shown at
once; when one is finished it fades out and the next queued title fades in.
Files are renamed in place and a dropped folder holding one title is renamed
to the Plex folder form. Everything applied is journaled and can be undone.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QEasingCurve, QModelIndex, QPoint,
                            QPropertyAnimation, Qt, QThread, Signal)
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter,
                               QStackedWidget, QTableView, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from .. import __version__, config
from .. import update as ota
from ..cli import scan
from ..journal import apply_ops, undo_last
from ..match import MatchResult, match_all
from ..parse import COMPANION_EXTS, VIDEO_EXTS, parse_file
from ..plan import build_plan, planned_folder_name, title_groups

MEDIA_EXTS = VIDEO_EXTS | COMPANION_EXTS
MAX_VISIBLE = 4
FADE_MS = 450


# ------------------------------------------------------------------ workers

class UpdateCheckWorker(QThread):
    found = Signal(object)          # Update | None

    def run(self) -> None:
        self.found.emit(ota.check_latest())


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)     # done, total bytes
    finished_path = Signal(object)  # Path | None

    def __init__(self, upd, parent=None) -> None:
        super().__init__(parent)
        self.upd = upd

    def run(self) -> None:
        try:
            path = ota.download(self.upd, progress=self.progress.emit)
        except Exception:
            path = None
        self.finished_path.emit(path)


class MatchWorker(QThread):
    done = Signal(list)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, paths: list[Path], kind: str, season: int | None, recursive: bool,
                 naming: dict, parent=None):
        super().__init__(parent)
        self.paths, self.kind, self.season, self.recursive, self.naming = paths, kind, season, recursive, naming

    def run(self) -> None:
        try:
            files = []
            for p in self.paths:
                if p.is_dir():
                    files += scan(p, self.recursive)
                elif p.is_file() and p.suffix.casefold() in MEDIA_EXTS:
                    files.append(parse_file(p, p.parent.parent if p.parent.parent != p.parent else p.parent))
            self.status.emit(f"Matching {len(files)} file(s)…")
            results = match_all(files, kind=self.kind, season=self.season)
            self.status.emit("Building names…")
            build_plan([r for r in results if r.status != "UNMATCHED"], **self.naming)
            self.done.emit(results)
        except Exception as e:  # surface, never swallow
            self.failed.emit(f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------ model

COLS = ["", "Status", "Original name", "New name", "Conf."]
TINT = {
    "AUTO": QColor(46, 160, 67, 45),
    "REVIEW": QColor(255, 170, 0, 55),
    "UNMATCHED": QColor(128, 128, 128, 35),
    "DONE": QColor(60, 130, 230, 45),
}


class ResultsModel(QAbstractTableModel):
    def __init__(self, results: list[MatchResult] | None = None) -> None:
        super().__init__()
        self.rows: list[MatchResult] = []
        self.checked: list[bool] = []
        self.done: list[bool] = []
        if results:
            self.set_results(results)

    def set_results(self, results: list[MatchResult]) -> None:
        self.beginResetModel()
        self.rows = sorted(results, key=lambda r: str(r.file.path).casefold())
        self.checked = [r.status == "AUTO" and bool(r.new_name) for r in self.rows]
        self.done = [False] * len(self.rows)
        self.endResetModel()

    def replace_rows(self, results: list[MatchResult]) -> int:
        by_path = {str(r.file.path).casefold(): r for r in results}
        n = 0
        for i, old in enumerate(self.rows):
            new = by_path.get(str(old.file.path).casefold())
            if new is not None:
                self.rows[i], self.done[i] = new, False
                self.checked[i] = new.status == "AUTO" and bool(new.new_name)
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLS) - 1))
                n += 1
        return n

    def mark_done(self, paths: set[str]) -> None:
        for i, r in enumerate(self.rows):
            if str(r.file.path).casefold() in paths:
                self.done[i], self.checked[i] = True, False
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLS) - 1))

    def status_of(self, i: int) -> str:
        return "DONE" if self.done[i] else self.rows[i].status

    def selected_results(self) -> list[MatchResult]:
        return [r for r, c, d in zip(self.rows, self.checked, self.done) if c and r.new_name and not d]

    def pending(self) -> int:
        """Rows that could still be renamed (matched, not yet done)."""
        return sum(1 for r, d in zip(self.rows, self.done) if r.new_name and not d)

    def set_checked_rows(self, indexes: list[int], value: bool) -> None:
        for i in indexes:
            if self.rows[i].new_name and not self.done[i]:
                self.checked[i] = value
                self.dataChanged.emit(self.index(i, 0), self.index(i, 0))

    def counts(self) -> dict[str, int]:
        c = {"AUTO": 0, "REVIEW": 0, "UNMATCHED": 0, "DONE": 0}
        for i in range(len(self.rows)):
            c[self.status_of(i)] += 1
        return c

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLS[section]
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0 and self.rows[index.row()].new_name and not self.done[index.row()]:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        i, col = index.row(), index.column()
        r = self.rows[i]
        status = self.status_of(i)
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            if not r.new_name or self.done[i]:
                return None
            return Qt.CheckState.Checked if self.checked[i] else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 1:
                return status
            if col == 2:
                return r.file.path.name
            if col == 3:
                if status == "UNMATCHED":
                    flagged = [t for t in r.trace if t.startswith("!")]
                    return "— " + (flagged[0] if flagged else (r.trace[-1] if r.trace else "no evidence"))
                return r.new_name or "(name unchanged)"
            if col == 4:
                return f"{r.confidence:.2f}"
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 2:
                return str(r.file.path)
            if col == 3:
                return "\n".join(r.trace[-4:])
        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(TINT[status])
        if role == Qt.ItemDataRole.ForegroundRole and status == "UNMATCHED":
            return QBrush(QColor(110, 110, 110))
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (1, 4):
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            self.checked[index.row()] = (Qt.CheckState(value) == Qt.CheckState.Checked)
            self.dataChanged.emit(index, index)
            return True
        return False


# ------------------------------------------------------------------ sections

@dataclass
class Section:
    title: str
    results: list[MatchResult]
    root: Path | None            # dropped folder this section came from, if any
    folder_new_name: str | None  # planned folder name for folder_src, if a rename is planned
    kind: str = ""
    subtitle: str = ""
    folder_src: Path | None = None   # the folder being renamed: the root, or a movie's own subfolder


def split_sections(results: list[MatchResult], roots: list[Path], prefer_original: bool,
                   rename_folders: bool, movie_scheme: str = "filebot") -> list[Section]:
    """One section per (dropped root, title). Unmatched files group by their folder."""
    dirs = [r for r in roots if r.is_dir()]

    def root_of(p: Path) -> Path | None:
        best = None
        for d in dirs:
            try:
                p.relative_to(d)
            except ValueError:
                continue
            if best is None or len(str(d)) > len(str(best)):
                best = d
        return best

    buckets: dict[tuple, list[MatchResult]] = {}
    order: list[tuple] = []
    root_paths: dict[str, Path] = {}
    groups = title_groups(results)
    for r in results:
        root = root_of(r.file.path)
        key = groups.get(id(r)) or ("?", str(r.file.path.parent).casefold())
        k = (str(root).casefold() if root else "", key)
        if root is not None:
            root_paths[k[0]] = root
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(r)

    # does each root hold exactly one title? then its folder can be renamed
    titles_per_root: dict[str, set] = {}
    for (root_s, key) in buckets:
        if key[0] != "?":
            titles_per_root.setdefault(root_s, set()).add(key)

    sections: list[Section] = []
    for k in sorted(order, key=lambda k: (roots_index(k[0], dirs), k[1][0] == "?", str(k[1]))):
        root_s, key = k
        rows = buckets[k]
        root = root_paths.get(root_s) if root_s else None
        first = next((r for r in rows if r.status != "UNMATCHED"), None)
        if key[0] == "?" or first is None:
            title = f"Unmatched · {rows[0].file.path.parent.name}"
            kind, sub = "unmatched", f"{len(rows)} file(s)"
        elif first.kind == "tv":
            title = first.show_original if prefer_original and first.show_original else first.show
            title += f" ({first.show_year})" if first.show_year else ""
            kind = "tv"
            ids = first.show_ids or {}
            idtxt = next((f"{kk}-{ids[kk]}" for kk in ("tmdb", "tvdb", "anilist", "tvmaze") if ids.get(kk)), "")
            sub = f"{len(rows)} file(s) · {idtxt}".rstrip(" ·")
        else:
            title = first.movie_original if prefer_original and first.movie_original else first.movie_title
            title += f" ({first.movie_year})" if first.movie_year else ""
            kind = "movie"
            sub = f"{len(rows)} file(s) · tmdb-{first.tmdb_id}" if first.tmdb_id else f"{len(rows)} file(s)"
        folder_new, folder_src = None, None
        if rename_folders and root is not None and kind != "unmatched":
            if len(titles_per_root.get(root_s, ())) == 1:
                folder_new = planned_folder_name(results, root, prefer_original, movie_scheme)
                folder_src = root if folder_new else None
            elif kind == "movie":
                # a movie in its own subfolder of a shared drop still gets its folder renamed
                parents = {r.file.path.parent for r in rows}
                if len(parents) == 1 and (par := parents.pop()) != root:
                    folder_new = planned_folder_name(results, par, prefer_original, movie_scheme)
                    folder_src = par if folder_new else None
        sections.append(Section(title=title or "?", results=rows, root=root,
                                folder_new_name=folder_new, kind=kind, subtitle=sub,
                                folder_src=folder_src))
    return sections


def roots_index(root_s: str, dirs: list[Path]) -> int:
    for i, d in enumerate(dirs):
        if str(d).casefold() == root_s:
            return i
    return len(dirs)


class SectionPanel(QFrame):
    apply_requested = Signal(object)
    dismiss_requested = Signal(object)
    current_changed = Signal(object)          # MatchResult | None
    rematch_requested = Signal(list, object, object)   # paths, kind, season

    def __init__(self, section: Section, parent=None) -> None:
        super().__init__(parent)
        self.section = section
        self.model = ResultsModel(section.results)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("SectionPanel")
        self.setStyleSheet("#SectionPanel { border: 1px solid palette(mid); border-radius: 6px; }")
        self._effect: QGraphicsOpacityEffect | None = None
        self._anim: QPropertyAnimation | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        head = QHBoxLayout()
        self.title = QLabel(section.title)
        f = QFont()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setToolTip("Dismiss this title")
        close.clicked.connect(lambda: self.dismiss_requested.emit(self))
        head.addWidget(close)
        lay.addLayout(head)

        self.sub = QLabel(section.subtitle)
        self.sub.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.sub)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 26)
        self.table.setColumnWidth(1, 84)
        self.table.setColumnWidth(4, 50)
        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, _p: self.current_changed.emit(self.model.rows[cur.row()] if cur.isValid() else None))
        lay.addWidget(self.table, 1)

        self.folder_label = QLabel()
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.folder_label)

        foot = QHBoxLayout()
        self.counts = QLabel()
        foot.addWidget(self.counts, 1)
        accept = QPushButton("Accept review")
        accept.clicked.connect(lambda: self.model.set_checked_rows(
            [i for i in range(len(self.model.rows)) if self.model.status_of(i) == "REVIEW"], True))
        foot.addWidget(accept)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(lambda: self.apply_requested.emit(self))
        foot.addWidget(self.apply_btn)
        lay.addLayout(foot)

        self.model.dataChanged.connect(lambda *_: self.refresh())
        self.model.modelReset.connect(self.refresh)
        self.refresh()

    # -- state
    def refresh(self) -> None:
        c = self.model.counts()
        n = len(self.model.selected_results())
        self.counts.setText(f"{c['AUTO']} auto · {c['REVIEW']} review · {c['UNMATCHED']} unmatched"
                            + (f" · {c['DONE']} done" if c["DONE"] else ""))
        self.apply_btn.setEnabled(n > 0)
        self.apply_btn.setText(f"Apply ({n})" if n else "Apply")
        root, new = self.section.root, self.section.folder_new_name
        src_dir = self.section.folder_src or root
        if src_dir is not None and new and not self.model.counts()["DONE"]:
            self.folder_label.setText(f"Folder: {src_dir.name}  →  {new}")
        elif root is not None and self.model.counts()["DONE"]:
            self.folder_label.setText(f"Folder: {root.name}")
        else:
            self.folder_label.setText("")

    def is_complete(self) -> bool:
        return self.model.pending() == 0

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def fade(self, target: float, on_done=None, start: float | None = None) -> None:
        """Animate opacity. The effect exists only while animating: a lingering
        QGraphicsOpacityEffect breaks table painting on some platforms."""
        if self._effect is None:
            self._effect = QGraphicsOpacityEffect(self)
            self._effect.setOpacity(1.0 if start is None else start)
            self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(FADE_MS)
        self._anim.setStartValue(self._effect.opacity() if start is None else start)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def finished():
            if target >= 1.0:          # fully visible again: drop the effect
                self.setGraphicsEffect(None)
                self._effect = None
            if on_done:
                on_done()
        self._anim.finished.connect(finished)
        self._anim.start()

    # -- context menu
    def _context_menu(self, pos: QPoint) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        menu = QMenu(self)
        menu.addAction("Accept", lambda: self.model.set_checked_rows(rows, True))
        menu.addAction("Reject", lambda: self.model.set_checked_rows(rows, False))
        menu.addSeparator()
        force = menu.addMenu("Re-match as")
        paths = [self.model.rows[i].file.path for i in rows]
        for kind in ("tv", "anime", "movie"):
            force.addAction(kind, lambda k=kind: self.rematch_requested.emit(paths, k, None))
        menu.addAction("Re-match with season…", lambda: self._ask_season(paths))
        menu.addSeparator()
        menu.addAction("Open containing folder", lambda: _open_folder(self.model.rows[rows[0]].file.path))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _ask_season(self, paths: list[Path]) -> None:
        n, ok = QInputDialog.getInt(self, "Season", "Season number for the selected files:", 1, 1, 99)
        if ok:
            self.rematch_requested.emit(paths, None, n)


def _open_folder(p: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        QDesktopServices.openUrl(p.parent.as_uri())


# ------------------------------------------------------------------ settings

class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self.key = QLineEdit(cfg.get("tmdb_api_key", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("free key from themoviedb.org → Settings → API")
        form.addRow("TMDb API key", self.key)

        self.tv_scheme = QComboBox()
        self.tv_scheme.addItem("Plex — Show (Year) - S01E02 - Title", "plex")
        self.tv_scheme.addItem("Simple — Show - S01E02 - Title", "simple")
        self.tv_scheme.setCurrentIndex(max(0, self.tv_scheme.findData(cfg.get("tv_scheme", "plex"))))
        form.addRow("TV names", self.tv_scheme)
        self.movie_scheme = QComboBox()
        self.movie_scheme.addItem("FileBot — Title.Dots (Year) [Director] 1080p.x265-GROUP", "filebot")
        self.movie_scheme.addItem("Simple — Title (Year)", "simple")
        self.movie_scheme.setCurrentIndex(max(0, self.movie_scheme.findData(cfg.get("movie_scheme", "filebot"))))
        form.addRow("Movie names", self.movie_scheme)

        self.rename_folders = QCheckBox("Rename a dropped folder to 'Title (Year) {tmdb-ID}'")
        self.rename_folders.setChecked(bool(cfg.get("rename_folders", True)))
        form.addRow("", self.rename_folders)
        self.original = QCheckBox("Prefer original-language titles (庆余年, not Joy of Life)")
        self.original.setChecked(bool(cfg.get("prefer_original_titles")))
        form.addRow("", self.original)
        self.recursive = QCheckBox("Scan dropped folders recursively")
        self.recursive.setChecked(bool(cfg.get("recursive", True)))
        form.addRow("", self.recursive)
        out_row = QHBoxLayout()
        self.output = QLineEdit(cfg.get("output_dir", ""))
        self.output.setPlaceholderText("empty = keep files where they are")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        out_row.addWidget(self.output)
        out_row.addWidget(browse)
        form.addRow("Organize into", out_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.output.text() or str(Path.home()))
        if d:
            self.output.setText(d)

    def values(self) -> dict:
        return {
            "tmdb_api_key": self.key.text().strip(),
            "tv_scheme": self.tv_scheme.currentData(),
            "movie_scheme": self.movie_scheme.currentData(),
            "rename_folders": self.rename_folders.isChecked(),
            "prefer_original_titles": self.original.isChecked(),
            "recursive": self.recursive.isChecked(),
            "output_dir": self.output.text().strip(),
        }


# ------------------------------------------------------------------ main window

class MainWindow(QMainWindow):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.paths: list[Path] = []
        self.worker: MatchWorker | None = None
        self.confirm_apply = True        # tests switch this off
        self.animate = True              # tests switch this off
        self.visible_panels: list[SectionPanel] = []
        self.queued: list[Section] = []
        self.setWindowTitle("mediarenamer")
        self.resize(1280, 760)
        self.setAcceptDrops(True)
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._refresh_counts()
        self._upd_check: UpdateCheckWorker | None = None
        self._upd_dl: UpdateDownloadWorker | None = None
        if ota.running_frozen():
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self.check_updates)

    # -- UI construction
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def act(text: str, slot, shortcut: str | None = None) -> QAction:
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            tb.addAction(a)
            return a

        act("Add folder…", self.add_folder, "Ctrl+O")
        act("Add files…", self.add_files, "Ctrl+Shift+O")
        self.act_match = act("Match", self.rematch_all, "F5")
        tb.addSeparator()
        self.act_apply = act("Apply all", self.apply_all, "Ctrl+Return")
        act("Undo last", self.undo, "Ctrl+Z")
        tb.addSeparator()
        act("Accept all review", self._accept_all_review)
        act("Clear", self.clear)
        tb.addSeparator()
        act("Settings…", self.open_settings)
        act("Check for updates", lambda: self.check_updates(manual=True))

        self.addToolBarBreak()
        opts = QToolBar("Options")
        opts.setMovable(False)
        self.addToolBar(opts)
        opts.addWidget(QLabel(" Match as: "))
        self.kind = QComboBox()
        self.kind.addItems(["auto", "tv", "anime", "movie"])
        opts.addWidget(self.kind)
        opts.addWidget(QLabel("   Season: "))
        self.season = QSpinBox()
        self.season.setRange(0, 99)
        self.season.setSpecialValueText("auto")
        self.season.setToolTip("Force a season for bare episode numbers (auto = infer from the batch)")
        opts.addWidget(self.season)
        hint = QLabel("   Options apply on the next Match (F5)")
        hint.setStyleSheet("color: palette(mid);")
        opts.addWidget(hint)

    def _build_central(self) -> None:
        self.stack = QStackedWidget()
        hint = QLabel("Drop folders or files here\n\nEach show or movie gets its own column.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(14)
        hint.setFont(f)
        hint.setStyleSheet("color: palette(mid);")
        self.stack.addWidget(hint)

        self.columns_host = QWidget()
        self.columns = QHBoxLayout(self.columns_host)
        self.columns.setContentsMargins(6, 6, 6, 6)
        self.columns.setSpacing(8)
        self.stack.addWidget(self.columns_host)

        self.trace = QPlainTextEdit()
        self.trace.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.trace.setFont(mono)
        self.trace.setPlaceholderText("Select a row to see why it was matched the way it was.")

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.stack)
        split.addWidget(self.trace)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

    def _build_statusbar(self) -> None:
        self.counts = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(160)
        self.progress.hide()
        self.statusBar().addWidget(self.counts, 1)
        self.statusBar().addPermanentWidget(self.progress)

    # -- options
    def _naming(self) -> dict:
        out = Path(self.cfg["output_dir"]) if self.cfg.get("output_dir") else None
        return dict(output=out, prefer_original=bool(self.cfg.get("prefer_original_titles")),
                    tv_scheme=self.cfg.get("tv_scheme", "plex"),
                    movie_scheme=self.cfg.get("movie_scheme", "filebot"))

    def _refresh_counts(self) -> None:
        c = {"AUTO": 0, "REVIEW": 0, "UNMATCHED": 0, "DONE": 0}
        planned = 0
        for p in self.visible_panels:
            for k, v in p.model.counts().items():
                c[k] += v
            planned += len(p.model.selected_results())
        queued = len(self.queued)
        self.counts.setText(
            f"{len(self.visible_panels)} title(s) shown" + (f", {queued} queued" if queued else "")
            + f"   |   {c['AUTO']} auto   {c['REVIEW']} review   {c['UNMATCHED']} unmatched   "
            f"{c['DONE']} done   |   {planned} selected to rename")
        self.act_apply.setEnabled(planned > 0)
        self.stack.setCurrentIndex(1 if (self.visible_panels or self.queued) else 0)

    def _busy(self, on: bool, text: str = "") -> None:
        self.progress.setVisible(on)
        self.act_match.setEnabled(not on)
        self.setCursor(Qt.CursorShape.BusyCursor if on else Qt.CursorShape.ArrowCursor)
        if text:
            self.statusBar().showMessage(text, 0 if on else 4000)
        elif not on:
            self.statusBar().clearMessage()

    def _show_trace(self, r: MatchResult | None) -> None:
        if r is None:
            self.trace.clear()
            return
        lines = [str(r.file.path), "", "parse:"] + [f"  {t}" for t in r.file.trace]
        lines += ["", "match:"] + [f"  {t}" for t in r.trace]
        if r.new_name:
            lines += ["", f"-> {r.new_name}   (confidence {r.confidence:.2f}, {r.status})"]
        self.trace.setPlainText("\n".join(lines))

    def _accept_all_review(self) -> None:
        for p in self.visible_panels:
            p.model.set_checked_rows(
                [i for i in range(len(p.model.rows)) if p.model.status_of(i) == "REVIEW"], True)

    # -- input
    def add_paths(self, paths: list[Path]) -> None:
        new = [p for p in paths if p not in self.paths]
        if not new:
            return
        self.paths.extend(new)
        recent = [str(p) for p in new if p.is_dir()] + list(self.cfg.get("recent_paths", []))
        self.cfg["recent_paths"] = list(dict.fromkeys(recent))[:10]
        config.save(self.cfg)
        self._start_match(self.paths, replace=True)

    def add_folder(self) -> None:
        start = (self.cfg.get("recent_paths") or [str(Path.home())])[0]
        d = QFileDialog.getExistingDirectory(self, "Add folder", start)
        if d:
            self.add_paths([Path(d)])

    def add_files(self) -> None:
        start = (self.cfg.get("recent_paths") or [str(Path.home())])[0]
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", start, "Media files (*.*)")
        if files:
            self.add_paths([Path(f) for f in files])

    def clear(self) -> None:
        self.paths.clear()
        self.queued.clear()
        for p in list(self.visible_panels):
            self._remove_panel(p)
        self.trace.clear()
        self._refresh_counts()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    # -- matching
    def _start_match(self, paths: list[Path], replace: bool, kind: str | None = None,
                     season: int | None = None) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "A match is already running.")
            return
        k = kind or self.kind.currentText()
        s = season if season is not None else (self.season.value() or None)
        self.worker = MatchWorker(paths, k, s, bool(self.cfg.get("recursive", True)), self._naming(), parent=self)
        self.worker.status.connect(lambda t: self._busy(True, t))
        self.worker.failed.connect(self._match_failed)
        self.worker.done.connect(self._match_done if replace else self._rematch_done)
        self._busy(True, "Scanning…")
        self.worker.start()

    def rematch_all(self) -> None:
        if self.paths:
            self._start_match(self.paths, replace=True)

    def _match_done(self, results: list) -> None:
        for p in list(self.visible_panels):
            self._remove_panel(p)
        self.queued = split_sections(results, self.paths, bool(self.cfg.get("prefer_original_titles")),
                                     bool(self.cfg.get("rename_folders", True)),
                                     self.cfg.get("movie_scheme", "filebot"))
        self._fill_slots()
        self._busy(False, f"Matched {len(results)} file(s) in {len(self.queued) + len(self.visible_panels)} title(s)")
        if self.visible_panels and self.visible_panels[0].model.rows:
            self.visible_panels[0].table.selectRow(0)

    def _rematch_done(self, results: list) -> None:
        n = sum(p.model.replace_rows(results) for p in self.visible_panels)
        for p in self.visible_panels:
            p.refresh()
        self._refresh_counts()
        self._busy(False, f"Re-matched {n} file(s)")

    def _match_failed(self, msg: str) -> None:
        self._busy(False)
        QMessageBox.critical(self, "Matching failed", msg)

    # -- columns
    def _fill_slots(self) -> None:
        while self.queued and len(self.visible_panels) < MAX_VISIBLE:
            self._add_panel(self.queued.pop(0))
        self._refresh_counts()

    def _add_panel(self, section: Section) -> None:
        panel = SectionPanel(section)
        panel.apply_requested.connect(self.apply_panel)
        panel.dismiss_requested.connect(self._retire)
        panel.current_changed.connect(self._show_trace)
        panel.rematch_requested.connect(lambda paths, k, s: self._start_match(paths, False, k, s))
        panel.model.dataChanged.connect(lambda *_: self._refresh_counts())
        self.visible_panels.append(panel)
        self.columns.addWidget(panel, 1)
        if self.animate:
            panel.fade(1.0, start=0.0)

    def _remove_panel(self, panel: SectionPanel) -> None:
        if panel in self.visible_panels:
            self.visible_panels.remove(panel)
        self.columns.removeWidget(panel)
        panel.setParent(None)
        panel.deleteLater()
        shown = self.trace.toPlainText().split("\n", 1)[0]
        if any(str(r.file.path) == shown for r in panel.model.rows):
            self.trace.clear()

    def _retire(self, panel: SectionPanel) -> None:
        """Fade a finished column out, then let the next queued title in."""
        if panel not in self.visible_panels:
            return
        if not self.animate:
            self._remove_panel(panel)
            self._fill_slots()
            return
        panel.setEnabled(False)

        def done():
            self._remove_panel(panel)
            self._fill_slots()
        panel.fade(0.0, done)

    # -- apply / undo
    def apply_panel(self, panel: SectionPanel) -> None:
        selected = panel.model.selected_results()
        if not selected:
            return
        roots = [panel.section.root] if (panel.section.root
                                         and self.cfg.get("rename_folders", True)) else []
        # the folder is renamed only once every file of this title is accepted
        if roots and len(selected) < panel.model.pending():
            roots = []
        ops = build_plan(selected, rename_roots=roots, **self._naming())
        if self.confirm_apply:
            preview = "\n".join(f"{o.src.name}\n   → {o.dst.name}" for o in ops[:8])
            more = f"\n… and {len(ops) - 8} more" if len(ops) > 8 else ""
            reply = QMessageBox.question(
                self, "Apply renames", f"{panel.section.title}\nRename {len(ops)} item(s)?\n\n{preview}{more}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        n, errors = apply_ops(ops)
        failed = {e.split(":")[0].casefold() for e in errors}
        panel.model.mark_done({str(o.src).casefold() for o in ops if o.result is not None} - failed)
        for folder_op in (o for o in ops if o.result is None):
            if str(folder_op.src).casefold() in failed:
                continue
            # files now live under the new folder name; keep paths truthful
            self.paths = [folder_op.dst if p == folder_op.src else p for p in self.paths]
            if panel.section.root == folder_op.src:
                panel.section.root = folder_op.dst
            panel.section.folder_new_name = None
        panel.refresh()
        self._refresh_counts()
        msg = f"Renamed {n} item(s). Undo with Ctrl+Z."
        if errors:
            QMessageBox.warning(self, "Applied with problems", msg + "\n\nProblems:\n" + "\n".join(errors[:10]))
        else:
            self.statusBar().showMessage(msg, 6000)
        if panel.is_complete():
            self._retire(panel)

    def apply_all(self) -> None:
        for panel in list(self.visible_panels):
            if panel.model.selected_results():
                self.apply_panel(panel)

    def undo(self) -> None:
        n, errors = undo_last()
        text = f"Restored {n} item(s)."
        if errors:
            QMessageBox.warning(self, "Undo", text + "\n\n" + "\n".join(errors[:10]))
        else:
            self.statusBar().showMessage(text, 6000)
        if n and self.paths:
            # a renamed folder may have been restored: re-resolve dropped paths
            self.paths = [p if p.exists() else _existing_sibling(p) for p in self.paths]
            self.paths = [p for p in self.paths if p is not None]
            self.rematch_all()

    # -- settings
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.update(dlg.values())
            config.save(self.cfg)
            if self.cfg.get("tmdb_api_key"):
                os.environ["TMDB_API_KEY"] = self.cfg["tmdb_api_key"]
            if self.paths:
                self.rematch_all()

    # -- OTA updates
    def check_updates(self, manual: bool = False) -> None:
        if self._upd_check and self._upd_check.isRunning():
            return
        self._upd_check = UpdateCheckWorker(self)
        self._upd_check.found.connect(lambda u: self._update_found(u, manual))
        self._upd_check.start()

    def _update_found(self, upd, manual: bool) -> None:
        if upd is None:
            if manual:
                QMessageBox.information(self, "Up to date",
                                        f"mediarenamer {__version__} is the latest version.")
            return
        notes = ("\n\n" + upd.notes[:600]) if upd.notes else ""
        if not ota.running_frozen():
            if manual:
                QMessageBox.information(
                    self, "Update available",
                    f"Version {upd.version} is on GitHub (you run {__version__} from source).\n"
                    f"Pull the repo to update.{notes}")
            return
        reply = QMessageBox.question(
            self, "Update available",
            f"mediarenamer {upd.version} is available (you have {__version__}).\n"
            f"Download and install now? The app restarts when done.{notes}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._upd_dl = UpdateDownloadWorker(upd, self)
        self._upd_dl.progress.connect(
            lambda d, t: self.statusBar().showMessage(
                f"Downloading update… {d / 1e6:.0f}/{t / 1e6:.0f} MB" if t else
                f"Downloading update… {d / 1e6:.0f} MB"))
        self._upd_dl.finished_path.connect(self._update_downloaded)
        self._upd_dl.start()

    def _update_downloaded(self, path) -> None:
        if path is None:
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "Update failed",
                                "The download did not finish. Try again later.")
            return
        try:
            ota.launch_installer(path)
        except OSError as e:
            self.statusBar().clearMessage()
            QMessageBox.warning(
                self, "Update failed",
                f"Could not start the installer ({e}).\n\n"
                f"It was saved to:\n{path}\nRun it yourself to update.")
            return
        QApplication.quit()


def _existing_sibling(p: Path) -> Path | None:
    """After undo of a folder rename the dropped path no longer exists; the
    journal restored the old name, which we do not know here, so fall back to
    the parent if nothing better is possible."""
    return p.parent if p.parent.exists() else None


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("mediarenamer")
    cfg = config.load()
    config.apply_env(cfg)
    win = MainWindow(cfg)
    win.show()
    paths = [Path(a) for a in (argv or sys.argv)[1:] if Path(a).exists()]
    if paths:
        win.add_paths(paths)
    return app.exec()
