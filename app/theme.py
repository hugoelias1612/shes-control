"""Identidad SHES compartida por ventanas, tablas y diálogos."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QFontDatabase
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

LOGO = Path(__file__).resolve().parents[1] / "assets" / "shes-logo.png"


def apply_theme(application):
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    application.setStyle("Fusion")
    application.setWindowIcon(QIcon(str(LOGO)))
    application.setStyleSheet("""
        QWidget { font-family: 'Segoe UI'; font-size: 12px; color: #302d29; }
        QMainWindow, QDialog { background: #ffffff; }
        QLabel { background: transparent; }
        QFrame#brand { background: #fff9e6; border-radius: 12px; }
        QLabel#heading { font-size: 23px; font-weight: 700; color: #d91c28; }
        QPushButton, QToolButton { background: #ffcf24; border: 1px solid #e5b714;
            border-radius: 7px; padding: 9px 12px; font-weight: 600; color: #302d29; }
        QPushButton:hover, QToolButton:hover { background: #ffe277; border-color: #be8d00; }
        QPushButton:pressed { background: #edb900; }
        QPushButton:disabled { background: #f0efeb; color: #908c84; border-color: #dedbd3; }
        QPushButton#danger { background: #d91c28; color: white; border-color: #bc1420; }
        QPushButton#danger:hover { background: #b71621; }
        QPushButton#secondary { background: white; border: 1px solid #d9d4c8; color: #625a48; }
        QLineEdit, QComboBox, QDateEdit, QPlainTextEdit, QTextEdit { background: white;
            border: 1px solid #d9d4c8; border-radius: 6px; padding: 7px; selection-background-color: #ffe277; selection-color: #302d29; }
        QComboBox::drop-down, QDateEdit::drop-down { width: 24px; border-left: 1px solid #e7dfcd; }
        QAbstractItemView { background: white; alternate-background-color: #fffcf2;
            selection-background-color: #fff0ad; selection-color: #302d29; border: 1px solid #e7e2d7; gridline-color: #eee9df; }
        QHeaderView::section { background: #fff3bf; color: #463d25; padding: 9px; border: 0; border-bottom: 2px solid #ffcf24; font-weight: 600; }
        QTabWidget::pane { border: 1px solid #e7e2d7; background: white; }
        QTabBar::tab { background: #f6f3eb; padding: 10px 14px; margin-right: 2px; }
        QTabBar::tab:selected { background: #ffcf24; color: #302d29; font-weight: 700; }
        QCheckBox, QRadioButton { spacing: 8px; padding: 4px; }
        QCheckBox::indicator { width: 17px; height: 17px; }
        QScrollBar:vertical { background: #f7f4ed; width: 12px; }
        QScrollBar::handle:vertical { background: #d4c7a7; min-height: 25px; border-radius: 5px; }
        QToolTip { background: #fff3bf; color: #302d29; border: 1px solid #e5b714; padding: 6px; }
    """)


def brand_header(title, subtitle=""):
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(6, 8, 6, 14)
    logo = QLabel()
    logo.setPixmap(QPixmap(str(LOGO)).scaled(205, 75, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    layout.addWidget(logo)
    words = QVBoxLayout()
    heading = QLabel(title)
    heading.setObjectName("heading")
    words.addWidget(heading)
    text = QLabel(subtitle)
    text.setWordWrap(True)
    words.addWidget(text)
    layout.addLayout(words, 1)
    return widget
