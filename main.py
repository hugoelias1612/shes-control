import sys
from pathlib import Path
from app.history import save_raw_load

# IMPORTAR módulos que usan pandas ANTES de PySide6
from app.importers import (
    validate_puntos,
    validate_pedidos,
    validate_porcliente,
)

from app.review_data import (
    build_review_session,
)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.review_window import ReviewWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.review_window = None

        self.setWindowTitle("SHES Control")
        self.resize(1150, 780)

        # ----------------------------------------------------
        # Archivos seleccionados
        # ----------------------------------------------------

        self.files = {
            "ctes": None,
            "resis": None,
            "pedidos": None,
            "porcliente": None,
        }

        self.results = {
            "ctes": None,
            "resis": None,
            "pedidos": None,
            "porcliente": None,
        }

        # ----------------------------------------------------
        # Datos fuera de GitHub
        # ----------------------------------------------------

        documents = Path.home() / "Documents"

        self.data_root = (
            documents
            / "SHES-Control-Datos"
        )

        self.history_root = (
            self.data_root
            / "HISTORIAL"
        )

        self.history_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        # ----------------------------------------------------
        # Interfaz
        # ----------------------------------------------------

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(
            28,
            24,
            28,
            24,
        )
        main_layout.setSpacing(18)

        title = QLabel("SHES Control")

        title.setStyleSheet(
            """
            font-size: 30px;
            font-weight: 700;
            """
        )

        subtitle = QLabel(
            "Carga y validación de jornada comercial"
        )

        subtitle.setStyleSheet(
            """
            font-size: 15px;
            color: #666666;
            """
        )

        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # ----------------------------------------------------
        # Fecha
        # ----------------------------------------------------

        self.date_label = QLabel(
            "Fecha de preventa: todavía no detectada"
        )

        self.date_label.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 600;
            padding: 10px;
            """
        )

        main_layout.addWidget(self.date_label)

        # ----------------------------------------------------
        # Tarjetas de archivos
        # ----------------------------------------------------

        files_layout = QHBoxLayout()
        files_layout.setSpacing(12)

        self.ctes_card = self.create_file_card(
            "Puntos de Venta",
            "CORRIENTES",
            lambda: self.load_puntos("ctes"),
        )

        self.resis_card = self.create_file_card(
            "Puntos de Venta",
            "RESISTENCIA",
            lambda: self.load_puntos("resis"),
        )

        self.pedidos_card = self.create_file_card(
            "Reporte",
            "PEDIDOS",
            self.load_pedidos,
        )

        self.porcliente_card = self.create_file_card(
            "Detalle",
            "POR CLIENTE",
            self.load_porcliente,
        )

        files_layout.addWidget(
            self.ctes_card["frame"]
        )

        files_layout.addWidget(
            self.resis_card["frame"]
        )

        files_layout.addWidget(
            self.pedidos_card["frame"]
        )

        files_layout.addWidget(
            self.porcliente_card["frame"]
        )

        main_layout.addLayout(files_layout)

        # ----------------------------------------------------
        # Resultados
        # ----------------------------------------------------

        results_title = QLabel(
            "Validación preliminar"
        )

        results_title.setStyleSheet(
            """
            font-size: 19px;
            font-weight: 650;
            """
        )

        main_layout.addWidget(results_title)

        self.summary = QTextEdit()

        self.summary.setReadOnly(True)

        self.summary.setPlaceholderText(
            "Cargá los cuatro archivos para comenzar."
        )

        self.summary.setStyleSheet(
            """
            QTextEdit {
                background-color: white;
                border: 1px solid #dddddd;
                border-radius: 8px;
                padding: 10px;
                font-family: Consolas;
                font-size: 13px;
            }
            """
        )

        main_layout.addWidget(
            self.summary,
            1,
        )

        # ----------------------------------------------------
        # Botón guardar
        # ----------------------------------------------------

        self.save_button = QPushButton(
            "VALIDAR Y GUARDAR CARGA"
        )

        self.save_button.setEnabled(False)

        self.save_button.setFixedHeight(50)

        self.save_button.clicked.connect(
            self.save_load
        )

        self.save_button.setStyleSheet(
            """
            QPushButton {
                background-color: #202020;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
            }

            QPushButton:hover {
                background-color: #303030;
            }

            QPushButton:disabled {
                background-color: #bbbbbb;
                color: #eeeeee;
            }
            """
        )

        main_layout.addWidget(
            self.save_button
        )

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f4f4f4;
            }
            """
        )

        self.refresh_summary()

    # ========================================================
    # TARJETA
    # ========================================================

    def create_file_card(
        self,
        title_text,
        subtitle_text,
        action,
    ):
        frame = QFrame()

        frame.setMinimumHeight(170)

        frame.setStyleSheet(
            """
            QFrame {
                background-color: white;
                border: 1px solid #dddddd;
                border-radius: 10px;
            }
            """
        )

        layout = QVBoxLayout(frame)

        title = QLabel(title_text)

        title.setStyleSheet(
            """
            font-size: 13px;
            color: #777777;
            """
        )

        subtitle = QLabel(subtitle_text)

        subtitle.setStyleSheet(
            """
            font-size: 17px;
            font-weight: 700;
            """
        )

        status = QLabel(
            "⚪ Sin cargar"
        )

        status.setWordWrap(True)

        status.setStyleSheet(
            """
            font-size: 12px;
            color: #777777;
            """
        )

        button = QPushButton(
            "Seleccionar Excel"
        )

        button.setCursor(
            Qt.PointingHandCursor
        )

        button.clicked.connect(action)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(status)
        layout.addStretch()
        layout.addWidget(button)

        return {
            "frame": frame,
            "status": status,
            "button": button,
        }

    # ========================================================
    # SELECCIONAR ARCHIVO
    # ========================================================

    def choose_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo Excel",
            "",
            "Excel (*.xlsx)",
        )

        return path

    # ========================================================
    # PUNTOS
    # ========================================================

    def load_puntos(self, region_key):
        path = self.choose_excel()

        if not path:
            return

        region_name = (
            "Corrientes"
            if region_key == "ctes"
            else "Resistencia"
        )

        result = validate_puntos(
            path,
            region_name,
        )

        self.files[region_key] = path
        self.results[region_key] = result

        card = (
            self.ctes_card
            if region_key == "ctes"
            else self.resis_card
        )

        self.update_card(
            card,
            result,
        )

        # Si tenemos ambos Puntos, comprobamos fechas
        self.validate_cross_dates()

        # Si ya había pedidos cargados,
        # lo volvemos a validar con fecha preventa.
        self.revalidate_pedidos()

        self.refresh_summary()

    # ========================================================
    # PEDIDOS
    # ========================================================

    def load_pedidos(self):
        path = self.choose_excel()

        if not path:
            return

        preventa_date = (
            self.get_preventa_date()
        )

        result = validate_pedidos(
            path,
            preventa_date,
        )

        self.files["pedidos"] = path
        self.results["pedidos"] = result

        self.update_card(
            self.pedidos_card,
            result,
        )

        self.refresh_summary()

    def revalidate_pedidos(self):
        path = self.files["pedidos"]

        if not path:
            return

        preventa_date = (
            self.get_preventa_date()
        )

        if preventa_date is None:
            return

        result = validate_pedidos(
            path,
            preventa_date,
        )

        self.results["pedidos"] = result

        self.update_card(
            self.pedidos_card,
            result,
        )

    # ========================================================
    # POR CLIENTE
    # ========================================================

    def load_porcliente(self):
        path = self.choose_excel()

        if not path:
            return

        result = validate_porcliente(
            path
        )

        self.files["porcliente"] = path
        self.results["porcliente"] = result

        self.update_card(
            self.porcliente_card,
            result,
        )

        self.refresh_summary()

    # ========================================================
    # UI STATUS
    # ========================================================

    def update_card(
        self,
        card,
        result,
    ):
        if result.valid:
            card["status"].setText(
                f"✅ Correcto\n"
                f"{result.rows:,} filas"
            )

            card["status"].setStyleSheet(
                """
                font-size: 12px;
                color: #17823b;
                font-weight: 600;
                """
            )

        else:
            card["status"].setText(
                f"❌ Error\n"
                f"{result.message}"
            )

            card["status"].setStyleSheet(
                """
                font-size: 12px;
                color: #b3261e;
                font-weight: 600;
                """
            )

    # ========================================================
    # FECHA PREVENTA
    # ========================================================

    def get_preventa_date(self):
        ctes = self.results["ctes"]
        resis = self.results["resis"]

        if not ctes or not resis:
            return None

        if not ctes.valid or not resis.valid:
            return None

        if (
            ctes.preventa_date
            != resis.preventa_date
        ):
            return None

        return ctes.preventa_date

    def validate_cross_dates(self):
        ctes = self.results["ctes"]
        resis = self.results["resis"]

        if not ctes or not resis:
            return

        if not ctes.valid or not resis.valid:
            return

        if (
            ctes.preventa_date
            != resis.preventa_date
        ):
            self.date_label.setText(
                "❌ Las fechas de Corrientes y "
                "Resistencia no coinciden."
            )

            self.date_label.setStyleSheet(
                """
                font-size: 16px;
                font-weight: 700;
                color: #b3261e;
                padding: 10px;
                """
            )

            return

        date_value = ctes.preventa_date

        self.date_label.setText(
            "✅ Fecha de preventa detectada: "
            + date_value.strftime(
                "%d/%m/%Y"
            )
        )

        self.date_label.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 700;
            color: #17823b;
            padding: 10px;
            """
        )

    # ========================================================
    # RESUMEN
    # ========================================================

    def refresh_summary(self):
        lines = []

        preventa_date = (
            self.get_preventa_date()
        )

        if preventa_date:
            lines.append(
                "FECHA PREVENTA: "
                + preventa_date.strftime(
                    "%d/%m/%Y"
                )
            )

            lines.append("")

        labels = {
            "ctes": "PUNTOS CTES",
            "resis": "PUNTOS RESISTENCIA",
            "pedidos": "REPORTE PEDIDOS",
            "porcliente": "POR CLIENTE",
        }

        for key in [
            "ctes",
            "resis",
            "pedidos",
            "porcliente",
        ]:
            result = self.results[key]

            lines.append(
                f"--- {labels[key]} ---"
            )

            if result is None:
                lines.append(
                    "⚪ Todavía no cargado."
                )

                lines.append("")
                continue

            if not result.valid:
                lines.append(
                    "❌ ARCHIVO INVÁLIDO"
                )

                lines.append(
                    result.message
                )

                lines.append("")
                continue

            lines.append(
                f"✅ Archivo reconocido"
            )

            lines.append(
                f"Filas detectadas: "
                f"{result.rows:,}"
            )

            if result.preventa_date:
                lines.append(
                    "Fecha detectada: "
                    + result.preventa_date.strftime(
                        "%d/%m/%Y"
                    )
                )

            if result.report_date:
                lines.append(
                    "Fecha del reporte: "
                    + result.report_date.strftime(
                        "%d/%m/%Y"
                    )
                )

            lines.append(
                f"Vendedores detectados: "
                f"{len(result.sellers)}"
            )

            for seller in result.sellers:
                lines.append(
                    f"   • {seller}"
                )

            for warning in result.warnings:
                lines.append(
                    f"⚠️ {warning}"
                )

            lines.append("")

        # ----------------------------------------------------
        # Unión de vendedores
        # ----------------------------------------------------

        all_sellers = set()

        for result in self.results.values():
            if result and result.valid:
                all_sellers.update(
                    result.sellers
                )

        if all_sellers:
            lines.append(
                "=============================="
            )

            lines.append(
                "VENDEDORES DETECTADOS EN TOTAL"
            )

            lines.append(
                f"Cantidad: {len(all_sellers)}"
            )

            for seller in sorted(all_sellers):
                lines.append(
                    f"   • {seller}"
                )

        self.summary.setPlainText(
            "\n".join(lines)
        )

        self.update_save_button()

    # ========================================================
    # ¿SE PUEDE GUARDAR?
    # ========================================================

    def update_save_button(self):
        all_loaded = all(
            self.results[key] is not None
            for key in self.results
        )

        all_valid = all(
            self.results[key]
            and self.results[key].valid
            for key in self.results
        )

        preventa_ok = (
            self.get_preventa_date()
            is not None
        )

        self.save_button.setEnabled(
            all_loaded
            and all_valid
            and preventa_ok
        )

    # ========================================================
    # GUARDAR HISTORIAL
    # ========================================================

    def save_load(self):
        preventa_date = self.get_preventa_date()

        if preventa_date is None:
            QMessageBox.critical(
                self,
                "Error",
                "No hay una fecha de preventa válida.",
            )
            return

        if not all(
            result and result.valid
            for result in self.results.values()
        ):
            QMessageBox.critical(
                self,
                "Error",
                "Los cuatro archivos deben ser válidos.",
            )
            return

        try:
            destination = save_raw_load(self.history_root, preventa_date, self.files)
        except Exception as error:
            QMessageBox.critical(
                self,
                "Error guardando archivos",
                str(error),
            )
            return

        # ----------------------------------------------------
        # PREPARAR REVISIÓN DE VENDEDORES Y PEDIDOS
        # ----------------------------------------------------

        try:
            session = build_review_session(
                destination
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Error preparando revisión",
                "Los archivos fueron guardados correctamente, "
                "pero ocurrió un error al preparar la revisión.\n\n"
                f"{error}",
            )
            return

        QMessageBox.information(
            self,
            "Carga guardada",
            "✅ Jornada guardada correctamente.\n\n"
            f"Fecha de preventa: "
            f"{preventa_date.strftime('%d/%m/%Y')}\n\n"
            "Ahora se abrirá la revisión "
            "de vendedores y pedidos.",
        )

        # ----------------------------------------------------
        # ABRIR VENTANA DE REVISIÓN
        # ----------------------------------------------------

        self.review_window = ReviewWindow(
            session
        )

        self.review_window.show()


if __name__ == "__main__":
    app = QApplication(
        sys.argv
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )
