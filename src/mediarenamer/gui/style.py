"""App-wide theme: Fusion base, palette + stylesheet in dark or light,
following the system color scheme. Accent matches the app icon (teal).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

DARK = dict(window="#1e2126", base="#262a31", alt="#2c313a", border="#3a4049",
            text="#e6e8eb", muted="#8e97a3", accent="#2fc7b5", accent_hover="#43d6c4",
            accent_press="#22a595", accent_text="#0b2320", button="#2c313a",
            button_hover="#353b45", selection="#2fc7b5")
LIGHT = dict(window="#f4f5f7", base="#ffffff", alt="#eceef1", border="#d5dae1",
             text="#1d2228", muted="#6b7280", accent="#0e8f83", accent_hover="#12a192",
             accent_press="#0b7066", accent_text="#ffffff", button="#e8eaee",
             button_hover="#dde0e6", selection="#0e8f83")


def _palette(c: dict) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: c["window"], QPalette.ColorRole.Base: c["base"],
        QPalette.ColorRole.AlternateBase: c["alt"], QPalette.ColorRole.Button: c["button"],
        QPalette.ColorRole.Mid: c["muted"], QPalette.ColorRole.Highlight: c["selection"],
        QPalette.ColorRole.ToolTipBase: c["alt"],
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.ToolTipText):
        p.setColor(role, QColor(c["text"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(c["accent_text"]))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c["muted"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c["muted"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(c["muted"]))
    return p


def _qss(c: dict) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {c['window']}; }}

    QToolBar {{ background: {c['window']}; border: none; padding: 4px 6px; spacing: 4px; }}
    QToolBar::separator {{ background: {c['border']}; width: 1px; margin: 6px 6px; }}
    QToolButton {{ border: none; border-radius: 6px; padding: 5px 10px; color: {c['text']}; }}
    QToolButton:hover {{ background: {c['button_hover']}; }}
    QToolButton:pressed {{ background: {c['button']}; }}

    #SectionPanel {{ background: {c['base']}; border: 1px solid {c['border']};
                     border-radius: 10px; }}

    QPushButton {{ background: {c['button']}; color: {c['text']}; border: 1px solid {c['border']};
                   border-radius: 6px; padding: 5px 14px; }}
    QPushButton:hover {{ background: {c['button_hover']}; }}
    QPushButton:pressed {{ background: {c['alt']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['window']}; }}
    QPushButton[accent="true"] {{ background: {c['accent']}; color: {c['accent_text']};
                                  border: none; font-weight: 600; }}
    QPushButton[accent="true"]:hover {{ background: {c['accent_hover']}; }}
    QPushButton[accent="true"]:pressed {{ background: {c['accent_press']}; }}
    QPushButton[accent="true"]:disabled {{ background: {c['button']}; color: {c['muted']}; }}

    QTableView {{ background: {c['base']}; border: none; border-radius: 6px;
                  gridline-color: transparent; selection-background-color: {c['alt']};
                  selection-color: {c['text']}; }}
    QHeaderView::section {{ background: {c['base']}; color: {c['muted']}; border: none;
                            border-bottom: 1px solid {c['border']}; padding: 4px 6px; }}
    QTableView::item {{ padding: 2px; }}

    QComboBox, QSpinBox, QLineEdit {{ background: {c['base']}; color: {c['text']};
        border: 1px solid {c['border']}; border-radius: 6px; padding: 3px 8px; }}
    QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {c['base']}; color: {c['text']};
        border: 1px solid {c['border']}; selection-background-color: {c['alt']};
        selection-color: {c['text']}; }}

    QPlainTextEdit {{ background: {c['base']}; color: {c['text']};
        border: 1px solid {c['border']}; border-radius: 8px; }}

    QStatusBar {{ background: {c['window']}; color: {c['muted']}; }}
    QStatusBar::item {{ border: none; }}

    QProgressBar {{ background: {c['alt']}; border: none; border-radius: 5px;
                    height: 10px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}

    QSplitter::handle {{ background: {c['window']}; }}
    QSplitter::handle:vertical {{ height: 6px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px;
                                   min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px;
                                     min-width: 24px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QMenu {{ background: {c['base']}; color: {c['text']}; border: 1px solid {c['border']};
             border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 5px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c['alt']}; }}

    QToolTip {{ background: {c['alt']}; color: {c['text']}; border: 1px solid {c['border']};
                padding: 4px 6px; }}

    QCheckBox {{ color: {c['text']}; spacing: 6px; }}
    """


def is_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return True


def apply_theme(app: QApplication) -> None:
    c = DARK if is_dark(app) else LIGHT
    app.setStyle("Fusion")
    app.setPalette(_palette(c))
    app.setStyleSheet(_qss(c))
