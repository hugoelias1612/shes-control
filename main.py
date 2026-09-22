"""Entrada semanal. MainWindow conserva el import del flujo diario compatible."""
import sys
from app.daily_window import MainWindow
from app.week_window import WeeksWindow
from PySide6.QtWidgets import QApplication


def main():
    application = QApplication(sys.argv)
    from app.theme import apply_theme
    apply_theme(application)
    window = WeeksWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
