"""Run data work off the GUI thread, with a modal progress indicator."""
from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout


class DataThread(QThread):
    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.action()
        except Exception as error:
            self.error = error


class BusyDialog(QDialog):
    def reject(self):
        pass  # A transaction in progress must finish before its owner closes.

    def closeEvent(self, event):
        event.ignore()


def run_data(parent, action, message="Procesando datos…"):
    """Only data work belongs in action; widgets remain on the calling thread.

    Application modality prevents competing edits while the nested Qt event
    loop continues to paint and dispatch timers. The return contract is unchanged.
    """
    dialog = BusyDialog(parent)
    dialog.setWindowTitle("SHES Control")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(message))
    progress = QProgressBar()
    progress.setRange(0, 0)
    layout.addWidget(progress)
    worker = DataThread(action, dialog)
    worker.finished.connect(dialog.accept)
    worker.start()
    dialog.exec()
    worker.wait()
    dialog.deleteLater()
    if worker.error is not None:
        raise worker.error
    return worker.result
