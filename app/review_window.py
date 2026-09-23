from __future__ import annotations
from app.tables import configure_table

from typing import TYPE_CHECKING

from app.review_data import save_review
from app.processor import process_presale as process_presale_data

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.dashboard_window import DashboardWindow
from app.alerts_widget import AlertsWidget

if TYPE_CHECKING:
    from app.review_data import (
        LogicalOrder,
        ReviewSession,
    )


# ============================================================
# FORMATO
# ============================================================

def money(value: float) -> str:
    """
    1151585.32
    ->
    $1.151.585,32
    """

    formatted = (
        f"{value:,.2f}"
        .replace(
            ",",
            "X",
        )
        .replace(
            ".",
            ",",
        )
        .replace(
            "X",
            ".",
        )
    )

    return f"${formatted}"


def decimal_number(value: float) -> str:

    formatted = (
        f"{value:,.4f}"
        .rstrip("0")
        .rstrip(".")
    )

    return formatted


# ============================================================
# DETALLE DE ARTÍCULOS
# ============================================================

class ArticlesWidget(QFrame):

    def __init__(
        self,
        order: "LogicalOrder",
    ):
        super().__init__()

        self.order = order

        self.setVisible(False)

        self.setStyleSheet(
            """
            QFrame {
                background-color: #fff9e6;
                border: 1px solid #e4e4e4;
                border-radius: 7px;
            }
            """
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            10,
            10,
            10,
            10,
        )

        if not order.articles:

            label = QLabel(
                "No hay artículos atribuidos a este pedido. "
                "Consultá las alertas de conciliación."
            )

            label.setStyleSheet(
                "color: #777777;"
            )

            layout.addWidget(
                label
            )

            return

        table = QTableWidget()

        table.setColumnCount(5)

        table.setHorizontalHeaderLabels(
            [
                "Código",
                "Artículo",
                "Cantidad / bultos",
                "Bonificación",
                "Total",
            ]
        )

        table.setRowCount(
            len(
                order.articles
            )
        )

        from app.dashboard_window import NumericItem

        for row_index, article in enumerate(
            order.articles
        ):

            table.setItem(
                row_index,
                0,
                QTableWidgetItem(
                    article.code
                ),
            )

            table.setItem(
                row_index,
                1,
                QTableWidgetItem(
                    article.name
                ),
            )

            table.setItem(
                row_index,
                2,
                NumericItem(article.quantity, decimal_number(article.quantity)),
            )

            table.setItem(
                row_index,
                3,
                NumericItem(article.bonification, decimal_number(article.bonification)),
            )

            table.setItem(
                row_index,
                4,
                NumericItem(article.total, money(article.total)),
            )

        table.verticalHeader().setVisible(
            False
        )

        table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )






        configure_table(table)
        table.setMinimumHeight(
            min(
                260,
                70
                + len(
                    order.articles
                )
                * 28,
            )
        )

        layout.addWidget(
            table
        )


# ============================================================
# TARJETA DE PEDIDO
# ============================================================

class OrderCard(QFrame):

    def __init__(
        self,
        order: "LogicalOrder",
        sellers: list[str],
        on_changed,
    ):
        super().__init__()

        self.order = order
        self.on_changed = on_changed

        self.setStyleSheet(
            """
            QFrame {
                background-color: white;
                border: 1px solid #dddddd;
                border-radius: 9px;
            }
            """
        )

        main_layout = QVBoxLayout(
            self
        )

        main_layout.setContentsMargins(
            14,
            12,
            14,
            12,
        )

        main_layout.setSpacing(
            9
        )

        # ----------------------------------------------------
        # FILA 1
        # ----------------------------------------------------

        top = QHBoxLayout()

        client = QLabel(
            f"{order.client_code} - "
            f"{order.client_name}"
        )

        client.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 700;
            """
        )

        amount = QLabel(
            money(
                order.valid_total
            )
        )

        amount.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 700;
            """
        )

        top.addWidget(
            client
        )

        top.addStretch()

        top.addWidget(
            amount
        )

        main_layout.addLayout(
            top
        )

        # ----------------------------------------------------
        # INFO
        # ----------------------------------------------------

        order_numbers = (
            ", ".join(
                order.order_numbers
            )
            if order.order_numbers
            else "-"
        )

        info = QLabel(
            f"Pedido Chess: {order_numbers}"
            f"   ·   Alta: {order.alta_date}"
            f"   ·   Entrega: {order.delivery_date or '-'}"
        )

        info.setStyleSheet(
            """
            color: #666666;
            font-size: 12px;
            """
        )

        main_layout.addWidget(
            info
        )

        # ----------------------------------------------------
        # ESTADO
        # ----------------------------------------------------

        status_layout = QHBoxLayout()

        status = QLabel(
            order.status
        )

        if order.status == "ANULADO":

            status.setStyleSheet(
                """
                color: #b3261e;
                font-weight: 700;
                """
            )

        elif order.status.startswith(
            "MIXTO"
        ):

            status.setStyleSheet(
                """
                color: #a05a00;
                font-weight: 700;
                """
            )

        elif order.status == "FACTURADO":

            status.setStyleSheet(
                """
                color: #17823b;
                font-weight: 700;
                """
            )

        else:

            status.setStyleSheet(
                """
                color: #666666;
                font-weight: 700;
                """
            )

        status_layout.addWidget(
            status
        )

        if order.modified:

            modified = QLabel(
                "✏ Modificado"
            )

            modified.setStyleSheet(
                """
                color: #7b5d00;
                """
            )

            status_layout.addWidget(
                modified
            )

        status_layout.addStretch()

        main_layout.addLayout(
            status_layout
        )

        # ----------------------------------------------------
        # VENDEDOR
        # ----------------------------------------------------

        seller_layout = QHBoxLayout()

        original_label = QLabel(
            f"Original: "
            f"{order.original_seller}"
        )

        original_label.setStyleSheet(
            """
            color: #666666;
            """
        )

        seller_layout.addWidget(
            original_label
        )

        seller_layout.addStretch()

        seller_label = QLabel(
            "Asignar a:"
        )

        seller_layout.addWidget(
            seller_label
        )

        self.seller_combo = QComboBox()

        combo_sellers = list(
            sellers
        )

        if "SIN ASIGNAR" not in combo_sellers:
            combo_sellers.append(
                "SIN ASIGNAR"
            )

        self.seller_combo.addItems(
            combo_sellers
        )

        current_index = (
            self.seller_combo.findText(
                order.assigned_seller
            )
        )

        if current_index >= 0:

            self.seller_combo.setCurrentIndex(
                current_index
            )

        self.seller_combo.currentTextChanged.connect(
            self.change_seller
        )

        self.seller_combo.setMinimumWidth(
            220
        )

        seller_layout.addWidget(
            self.seller_combo
        )

        main_layout.addLayout(
            seller_layout
        )

        # ----------------------------------------------------
        # REASIGNACIÓN
        # ----------------------------------------------------

        self.reassignment_label = QLabel()

        self.reassignment_label.setStyleSheet(
            """
            color: #a05a00;
            font-weight: 600;
            """
        )

        main_layout.addWidget(
            self.reassignment_label
        )

        self.update_reassignment_label()

        # ----------------------------------------------------
        # ARTÍCULOS
        # ----------------------------------------------------

        self.articles_widget = ArticlesWidget(
            order
        )

        self.articles_button = QPushButton(
            f"Ver artículos "
            f"({len(order.articles)})"
        )

        self.articles_button.clicked.connect(
            self.toggle_articles
        )

        main_layout.addWidget(
            self.articles_button,
            alignment=Qt.AlignLeft,
        )

        main_layout.addWidget(
            self.articles_widget
        )

    def change_seller(
        self,
        seller: str,
    ):
        self.order.assigned_seller = seller

        self.update_reassignment_label()

        self.on_changed()

    def update_reassignment_label(
        self,
    ):
        if (
            self.order.assigned_seller
            != self.order.original_seller
        ):

            self.reassignment_label.setText(
                "↪ Reasignado: "
                f"{self.order.original_seller}"
                " → "
                f"{self.order.assigned_seller}"
            )

            self.reassignment_label.show()

        else:

            self.reassignment_label.hide()

    def toggle_articles(self):

        visible = (
            not self.articles_widget.isVisible()
        )

        self.articles_widget.setVisible(
            visible
        )

        if visible:

            self.articles_button.setText(
                "Ocultar artículos"
            )

        else:

            self.articles_button.setText(
                f"Ver artículos "
                f"({len(self.order.articles)})"
            )


# ============================================================
# PEDIDOS DE UN VENDEDOR
# ============================================================

class SellerOrdersDialog(QDialog):

    def __init__(
        self,
        seller: str,
        session: "ReviewSession",
        on_changed,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.seller = seller
        self.session = session
        self.on_changed = on_changed

        self.setWindowTitle(
            f"Pedidos · {seller}"
        )

        self.resize(
            1050,
            720,
        )

        main_layout = QVBoxLayout(
            self
        )

        title = QLabel(
            seller
        )

        title.setStyleSheet(
            """
            font-size: 24px;
            font-weight: 700;
            """
        )

        main_layout.addWidget(
            title
        )

        orders = (
            session.orders_originally_from(
                seller
            )
        )

        subtitle = QLabel(
            f"{len(orders)} pedidos lógicos "
            "detectados originalmente"
        )

        subtitle.setStyleSheet(
            "color: #666666;"
        )

        main_layout.addWidget(
            subtitle
        )

        if session.warnings:
            main_layout.addWidget(AlertsWidget(session.warnings))

        scroll = QScrollArea()

        scroll.setWidgetResizable(
            True
        )

        container = QWidget()

        orders_layout = QVBoxLayout(
            container
        )

        orders_layout.setContentsMargins(
            4,
            4,
            4,
            4,
        )

        orders_layout.setSpacing(
            10
        )

        if not orders:

            no_orders = QLabel(
                "Este vendedor aparece en SIGO, "
                "pero no tiene pedidos detectados."
            )

            no_orders.setStyleSheet(
                """
                color: #9a5a00;
                font-size: 14px;
                padding: 20px;
                """
            )

            orders_layout.addWidget(
                no_orders
            )

        else:

            for order in orders:

                card = OrderCard(
                    order=order,
                    sellers=session.sellers,
                    on_changed=self.handle_change,
                )

                orders_layout.addWidget(
                    card
                )

        orders_layout.addStretch()

        scroll.setWidget(
            container
        )

        main_layout.addWidget(
            scroll,
            1,
        )

        close_button = QPushButton(
            "Cerrar"
        )

        close_button.clicked.connect(
            self.accept
        )

        main_layout.addWidget(
            close_button
        )

    def handle_change(
        self,
    ):
        self.on_changed()


# ============================================================
# TARJETA DE VENDEDOR
# ============================================================

class SellerCard(QFrame):

    def __init__(
        self,
        seller: str,
        session: "ReviewSession",
        on_changed,
        open_orders,
    ):
        super().__init__()

        self.seller = seller
        self.session = session
        self.on_changed = on_changed
        self.open_orders = open_orders

        self.setStyleSheet(
            """
            QFrame {
                background-color: white;
                border: 1px solid #dddddd;
                border-radius: 10px;
            }
            """
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            15,
            14,
            15,
            14,
        )

        # ----------------------------------------------------
        # NOMBRE
        # ----------------------------------------------------

        top = QHBoxLayout()

        self.name_label = QLabel(
            seller
        )

        self.name_label.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 700;
            """
        )

        top.addWidget(
            self.name_label
        )

        top.addStretch()

        self.exclude_checkbox = QCheckBox(
            "Excluir del análisis"
        )

        self.exclude_checkbox.setChecked(
            seller
            in session.excluded_sellers
        )

        self.exclude_checkbox.stateChanged.connect(
            self.toggle_excluded
        )

        top.addWidget(
            self.exclude_checkbox
        )

        layout.addLayout(
            top
        )

        # ----------------------------------------------------
        # MÉTRICAS BÁSICAS
        # ----------------------------------------------------

        self.original_label = QLabel()
        self.valid_label = QLabel()
        self.orders_label = QLabel()
        self.clients_label = QLabel()

        for label in [
            self.original_label,
            self.valid_label,
            self.orders_label,
            self.clients_label,
        ]:

            label.setStyleSheet(
                """
                color: #555555;
                font-size: 13px;
                """
            )

            layout.addWidget(
                label
            )

        # ----------------------------------------------------
        # BOTÓN
        # ----------------------------------------------------

        details_button = QPushButton(
            "Ver pedidos"
        )

        details_button.clicked.connect(
            lambda:
            self.open_orders(
                self.seller
            )
        )

        layout.addWidget(
            details_button
        )

        self.refresh()

    def refresh(
        self,
    ):
        original = (
            self.session.original_presale(
                self.seller
            )
        )

        valid = (
            self.session.current_valid_presale(
                self.seller
            )
        )

        orders = (
            self.session.current_order_count(
                self.seller
            )
        )

        clients = (
            self.session.current_client_count(
                self.seller
            )
        )

        self.original_label.setText(
            "Preventa original: "
            + money(
                original
            )
        )

        self.valid_label.setText(
            "Preventa válida actual: "
            + money(
                valid
            )
        )

        self.orders_label.setText(
            f"Pedidos lógicos: {orders}"
        )

        self.clients_label.setText(
            f"Clientes: {clients}"
        )

        if (
            self.seller
            in self.session.excluded_sellers
        ):

            self.name_label.setText(
                f"{self.seller}  ·  EXCLUIDO"
            )

            self.name_label.setStyleSheet(
                """
                font-size: 16px;
                font-weight: 700;
                color: #999999;
                """
            )

        else:

            self.name_label.setText(
                self.seller
            )

            self.name_label.setStyleSheet(
                """
                font-size: 16px;
                font-weight: 700;
                color: #222222;
                """
            )

    def toggle_excluded(
        self,
        state,
    ):
        if self.exclude_checkbox.isChecked():

            self.session.excluded_sellers.add(
                self.seller
            )

        else:

            self.session.excluded_sellers.discard(
                self.seller
            )

        self.on_changed()


# ============================================================
# VENTANA PRINCIPAL DE REVISIÓN
# ============================================================

class ReviewWindow(QMainWindow):

    def __init__(
        self,
        session: "ReviewSession",
        save_callback=None,
        process_callback=None,
    ):
        super().__init__()

        self.session = session
        self.save_callback = save_callback or save_review
        self.process_callback = process_callback or process_presale_data
        self.review_confirmed = False
        self.dashboard_window = None

        self.cards = {}

        self.setWindowTitle(
            "SHES Control · Revisión de preventa"
        )

        self.resize(
            1250,
            800,
        )

        central = QWidget()

        self.setCentralWidget(
            central
        )

        main_layout = QVBoxLayout(
            central
        )
        from app.theme import brand_header
        main_layout.addWidget(brand_header("SHES Control"))

        main_layout.setContentsMargins(
            24,
            20,
            24,
            20,
        )

        main_layout.setSpacing(
            14
        )

        # ----------------------------------------------------
        # CABECERA
        # ----------------------------------------------------

        title = QLabel(
            "Revisión de preventa"
        )

        title.setStyleSheet(
            """
            font-size: 28px;
            font-weight: 700;
            """
        )

        main_layout.addWidget(
            title
        )

        subtitle = QLabel(
            "Fecha de preventa: "
            f"{session.preventa_date or '-'}"
        )

        subtitle.setStyleSheet(
            """
            color: #666666;
            font-size: 14px;
            """
        )

        main_layout.addWidget(
            subtitle
        )

        # ----------------------------------------------------
        # RESUMEN
        # ----------------------------------------------------

        if session.warnings:
            main_layout.addWidget(AlertsWidget(session.warnings))

        self.summary_label = QLabel()

        self.summary_label.setStyleSheet(
            """
            background-color: white;
            border: 1px solid #dddddd;
            border-radius: 8px;
            padding: 12px;
            font-size: 14px;
            font-weight: 600;
            """
        )

        main_layout.addWidget(
            self.summary_label
        )

        # ----------------------------------------------------
        # VENDEDORES
        # ----------------------------------------------------

        scroll = QScrollArea()

        scroll.setWidgetResizable(
            True
        )

        scroll_container = QWidget()

        self.grid = QGridLayout(
            scroll_container
        )

        self.grid.setSpacing(
            12
        )

        for index, seller in enumerate(
            session.sellers
        ):

            card = SellerCard(
                seller=seller,
                session=session,
                on_changed=self.handle_change,
                open_orders=self.open_seller_orders,
            )

            self.cards[
                seller
            ] = card

            row = index // 3
            column = index % 3

            self.grid.addWidget(
                card,
                row,
                column,
            )

        scroll.setWidget(
            scroll_container
        )

        main_layout.addWidget(
            scroll,
            1,
        )

        # ----------------------------------------------------
        # CONFIRMAR
        # ----------------------------------------------------

        self.confirm_button = QPushButton(
            "CONFIRMAR ASIGNACIONES"
        )


        self.confirm_button.setFixedHeight(
            50
        )

        self.confirm_button.setStyleSheet(
            """
            QPushButton {
                background-color: #d91c28;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
            }

            QPushButton:hover {
                background-color: #b71621;
            }
            """
        )

        self.confirm_button.clicked.connect(
            self.confirm_review
        )

        main_layout.addWidget(
            self.confirm_button
        )



        # ----------------------------------------------------
        # PROCESAR PREVENTA
        # ----------------------------------------------------

        self.process_button = QPushButton(
            "PROCESAR PREVENTA"
        )

        self.process_button.setFixedHeight(
            50
        )

        self.process_button.setEnabled(
            False
        )

        self.process_button.setStyleSheet(
            """
            QPushButton {
                background-color: #d91c28;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
            }

            QPushButton:hover {
                background-color: #b71621;
            }

            QPushButton:disabled {
                background-color: #aaaaaa;
                color: #eeeeee;
            }
            """
        )

        self.process_button.clicked.connect(
            self.process_presale
        )

        main_layout.addWidget(
            self.process_button
        )

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #fffdf7;
            }
            """
        )

        self.refresh()

    # ========================================================
    # ACTUALIZAR TODO
    # ========================================================

    def handle_change(
        self,
    ):
        self.review_confirmed = False
        self.session.confirmed_fingerprint = ""
        self.process_button.setEnabled(False)
        self.confirm_button.setEnabled(True)
        if self.dashboard_window is not None:
            self.dashboard_window.close()
            self.dashboard_window = None
        self.refresh()

    def refresh(
        self,
    ):
        for card in self.cards.values():
            card.refresh()

        detected = len(
            self.session.sellers
        )

        excluded = len(
            self.session.excluded_sellers
        )

        physical_orders = sum(
            len(
                order.order_numbers
            )
            for order in self.session.orders
        )

        logical_orders = len({(o.client_code, o.assigned_seller, o.preventa_day)
                              for o in self.session.orders})

        reassignments = (
            self.session.reassignment_count()
        )

        total = (
            self.session.company_valid_total()
        )

        self.summary_label.setText(
            f"Vendedores detectados: {detected}"
            f"   ·   "
            f"Pedidos Chess: {physical_orders}"
            f"   ·   "
            f"Pedidos lógicos: {logical_orders}"
            f"   ·   "
            f"Excluidos: {excluded}"
            f"   ·   "
            f"Reasignaciones: {reassignments}"
            f"   ·   "
            f"Preventa válida: {money(total)}"
        )

    # ========================================================
    # ABRIR PEDIDOS
    # ========================================================

    def open_seller_orders(
        self,
        seller: str,
    ):
        dialog = SellerOrdersDialog(
            seller=seller,
            session=self.session,
            on_changed=self.handle_change,
            parent=self,
        )

        dialog.exec()

        self.refresh()

    # ========================================================
    # CONFIRMAR
    # ========================================================

    def confirm_review(
        self,
    ):
        unassigned = [
            order
            for order in self.session.orders
            if (
                order.assigned_seller
                == "SIN ASIGNAR"
                and not order.fully_annulled
            )
        ]

        if unassigned:

            QMessageBox.warning(
                self,
                "Pedidos sin asignar",
                "Hay "
                f"{len(unassigned)} "
                "pedidos válidos marcados como "
                "SIN ASIGNAR.\n\n"
                "Asignálos antes de confirmar.",
            )

            return

        answer = QMessageBox.question(
            self,
            "Confirmar revisión",
            "¿Confirmar las asignaciones "
            "y exclusiones de vendedores?\n\n"
            "Esto guardará la revisión dentro "
            "de la carpeta de esta carga.",
            QMessageBox.Yes
            | QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        try:
            path = self.save_callback(self.session)
        except Exception as error:
            QMessageBox.critical(self, "Error guardando revisión", str(error))
            return

        QMessageBox.information(
            self,
            "Revisión guardada",
            "✅ Revisión confirmada.\n\n"
            "Se guardó:\n"
            f"{path}\n\n"
            "Todavía NO estamos cerrando "
            "premios ni números finales. "
            "Eso ocurrirá más adelante luego "
            "de importar las liquidaciones.",
        )

        self.review_confirmed = True

        self.process_button.setEnabled(
            True
        )

        self.confirm_button.setEnabled(
            False
        )

    # ========================================================
    # PROCESAR PREVENTA
    # ========================================================

    def process_presale(
        self,
    ):
        if not self.review_confirmed:

            QMessageBox.warning(
                self,
                "Revisión pendiente",
                "Primero confirmá las asignaciones.",
            )

            return

        try:
            data = self.process_callback(
                self.session
            )

        except Exception as error:

            QMessageBox.critical(
                self,
                "Error procesando preventa",
                str(error),
            )

            return

        QMessageBox.information(
            self,
            "Preventa procesada",
            "✅ Preventa procesada correctamente.\n\n"
            "Se creó:\n"
            "preventa_procesada.json\n\n"
            "Estos números todavía son PRELIMINARES.\n"
            "Los números finales y premios requerirán "
            "las liquidaciones.",
        )

        self.dashboard_window = DashboardWindow(
            data
        )

        self.dashboard_window.show()
