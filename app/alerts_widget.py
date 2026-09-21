"""Advertencias consultables sin ocupar permanentemente el área de trabajo."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QToolButton, QVBoxLayout


class AlertsWidget(QFrame):
    def __init__(self, warnings, parent=None):
        super().__init__(parent)
        messages = list(warnings)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.toggle = QToolButton()
        self.toggle.setText(f"Alertas de conciliación ({len(messages)})")
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setStyleSheet("QToolButton { color: #9a5a00; padding: 6px; }")
        self.toggle.setToolTip("Mostrar u ocultar los detalles de las alertas")
        layout.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText("\n\n".join(messages))
        self.details.setMaximumHeight(180)
        self.details.setMinimumHeight(100)
        self.details.setStyleSheet("QPlainTextEdit { color: #9a5a00; }")
        self.details.hide()
        layout.addWidget(self.details)
        self.toggle.toggled.connect(self.set_expanded)
        self.setVisible(bool(messages))

    def set_expanded(self, expanded):
        self.details.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
