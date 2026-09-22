from __future__ import annotations

from app.alerts_widget import AlertsWidget

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ============================================================
# FORMATO
# ============================================================

def money(value):
    formatted = (
        f"{value:,.0f}"
        .replace(",", ".")
    )

    return f"${formatted}"


def pct(value):
    return f"{value:.1f}%"


def number(value):
    return (
        f"{value:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


# ============================================================
# ITEM NUMÉRICO ORDENABLE
# ============================================================

class NumericItem(QTableWidgetItem):

    def __init__(
        self,
        value,
        text=None,
    ):
        super().__init__(
            text
            if text is not None
            else str(value)
        )

        self.value = (
            value
            if value is not None
            else 0
        )

    def __lt__(
        self,
        other,
    ):
        if isinstance(
            other,
            NumericItem,
        ):
            return (
                self.value
                < other.value
            )

        return super().__lt__(
            other
        )


# ============================================================
# TARJETA MÉTRICA
# ============================================================

class MetricCard(QFrame):

    def __init__(
        self,
        title,
        value,
    ):
        super().__init__()

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

        title_label = QLabel(
            title
        )

        title_label.setStyleSheet(
            """
            color: #777777;
            font-size: 12px;
            """
        )

        value_label = QLabel(
            value
        )

        value_label.setStyleSheet(
            """
            font-size: 23px;
            font-weight: 700;
            """
        )

        layout.addWidget(
            title_label
        )

        layout.addWidget(
            value_label
        )


# ============================================================
# GRÁFICO DE BARRAS SIMPLE
# ============================================================

class BarChart(QFrame):

    def __init__(self):
        super().__init__()

        self.data = []

        self.setMinimumHeight(
            300
        )

        self.setStyleSheet(
            """
            background-color: white;
            border: 1px solid #dddddd;
            border-radius: 10px;
            """
        )

    def set_data(
        self,
        data,
    ):
        self.data = data
        self.update()

    def paintEvent(
        self,
        event,
    ):
        super().paintEvent(
            event
        )

        if not self.data:
            return

        painter = QPainter(
            self
        )

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        rect = self.rect()

        left = 150
        right = 25
        top = 20
        bottom = 20

        usable_width = (
            rect.width()
            - left
            - right
        )

        usable_height = (
            rect.height()
            - top
            - bottom
        )

        data = self.data[
            :15
        ]

        maximum = max(
            value
            for _, value in data
        )

        if maximum <= 0:
            painter.end()
            return

        row_height = (
            usable_height
            / max(
                len(data),
                1,
            )
        )

        for index, (
            label,
            value,
        ) in enumerate(data):

            y = (
                top
                + index
                * row_height
            )

            painter.drawText(
                10,
                int(
                    y
                    + row_height
                    * 0.65
                ),
                label[:20],
            )

            width = (
                value
                / maximum
                * usable_width
            )

            painter.fillRect(
                left,
                int(
                    y
                    + row_height
                    * 0.20
                ),
                int(width),
                max(
                    int(
                        row_height
                        * 0.55
                    ),
                    4,
                ),
                self.palette().highlight(),
            )

        painter.end()


# ============================================================
# DETALLE VENDEDOR
# ============================================================

class SellerDetailDialog(QDialog):

    def __init__(
        self,
        seller_data,
        parent=None,
    ):
        super().__init__(
            parent
        )

        self.data = (
            seller_data
        )

        self.resize(
            1150,
            760,
        )

        self.setWindowTitle(
            seller_data[
                "seller"
            ]
        )

        main = QVBoxLayout(
            self
        )

        title = QLabel(
            seller_data[
                "seller"
            ]
        )

        title.setStyleSheet(
            """
            font-size: 27px;
            font-weight: 700;
            """
        )

        main.addWidget(
            title
        )

        metrics = QHBoxLayout()

        metrics.addWidget(
            MetricCard(
                "Venta",
                money(
                    seller_data[
                        "sale"
                    ]
                ),
            )
        )

        metrics.addWidget(
            MetricCard(
                "% Empresa",
                pct(
                    seller_data[
                        "company_share_pct"
                    ]
                ),
            )
        )

        metrics.addWidget(
            MetricCard(
                "Clientes con venta",
                str(
                    seller_data[
                        "buyers"
                    ]
                ),
            )
        )

        metrics.addWidget(
            MetricCard(
                "Ticket promedio",
                money(
                    seller_data[
                        "average_ticket"
                    ]
                ),
            )
        )

        metrics.addWidget(
            MetricCard(
                "Cobertura",
                pct(
                    seller_data[
                        "coverage_pct"
                    ]
                ),
            )
        )

        main.addLayout(
            metrics
        )

        second = QHBoxLayout()

        second.addWidget(
            MetricCard(
                "Asignados",
                str(
                    seller_data[
                        "assigned_clients"
                    ]
                ),
            )
        )

        second.addWidget(
            MetricCard(
                "Visitados",
                str(
                    seller_data[
                        "visited_clients"
                    ]
                ),
            )
        )

        second.addWidget(
            MetricCard(
                "No visitados",
                str(
                    seller_data[
                        "not_visited_clients"
                    ]
                ),
            )
        )

        second.addWidget(
            MetricCard(
                "Conversión",
                pct(
                    seller_data[
                        "conversion_pct"
                    ]
                ),
            )
        )

        second.addWidget(
            MetricCard(
                "Mix art./cliente",
                number(
                    seller_data[
                        "average_article_mix"
                    ]
                ),
            )
        )

        main.addLayout(
            second
        )

        tabs = QTabWidget()

        tabs.addTab(
            self.articles_table(),
            "Artículos",
        )

        tabs.addTab(
            self.providers_table(),
            "Proveedores",
        )

        main.addWidget(
            tabs,
            1,
        )

    def articles_table(
        self,
    ):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        table.setColumnCount(
            8
        )

        table.setHorizontalHeaderLabels(
            [
                "Código",
                "Artículo",
                "Proveedor",
                "Bultos",
                "Venta",
                "Clientes",
                "Cobertura",
                "% Venta",
            ]
        )

        articles = self.data[
            "articles"
        ]

        table.setRowCount(
            len(
                articles
            )
        )

        for row, article in enumerate(
            articles
        ):

            table.setItem(
                row,
                0,
                QTableWidgetItem(
                    article["code"]
                ),
            )

            table.setItem(
                row,
                1,
                QTableWidgetItem(
                    article["name"]
                ),
            )

            table.setItem(
                row,
                2,
                QTableWidgetItem(
                    article["provider"]
                ),
            )

            table.setItem(
                row,
                3,
                NumericItem(
                    article["quantity"],
                    number(
                        article[
                            "quantity"
                        ]
                    ),
                ),
            )

            table.setItem(
                row,
                4,
                NumericItem(
                    article["sale"],
                    money(
                        article["sale"]
                    ),
                ),
            )

            table.setItem(
                row,
                5,
                NumericItem(
                    article["clients"],
                ),
            )

            table.setItem(
                row,
                6,
                NumericItem(
                    article[
                        "buyer_coverage_pct"
                    ],
                    pct(
                        article[
                            "buyer_coverage_pct"
                        ]
                    ),
                ),
            )

        for row, article in enumerate(articles):
            table.setItem(row, 7, NumericItem(article["sale_share_pct"], pct(article["sale_share_pct"])))

        table.setSortingEnabled(
            True
        )

        table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.Stretch,
        )

        return table

    def providers_table(
        self,
    ):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        table.setColumnCount(
            7
        )

        table.setHorizontalHeaderLabels(
            [
                "Proveedor",
                "Venta",
                "% Venta",
                "Bultos",
                "Artículos",
                "Cobertura",
                "Clientes",
            ]
        )

        providers = self.data[
            "providers"
        ]

        table.setRowCount(
            len(
                providers
            )
        )

        for row, provider in enumerate(
            providers
        ):

            table.setItem(
                row,
                0,
                QTableWidgetItem(
                    provider[
                        "provider"
                    ]
                ),
            )

            table.setItem(
                row,
                1,
                NumericItem(
                    provider["sale"],
                    money(
                        provider[
                            "sale"
                        ]
                    ),
                ),
            )

            table.setItem(
                row,
                2,
                NumericItem(
                    provider[
                        "sale_share_pct"
                    ],
                    pct(
                        provider[
                            "sale_share_pct"
                        ]
                    ),
                ),
            )

            table.setItem(
                row,
                3,
                NumericItem(
                    provider[
                        "quantity"
                    ],
                    number(
                        provider[
                            "quantity"
                        ]
                    ),
                ),
            )

            table.setItem(
                row,
                4,
                NumericItem(
                    provider[
                        "article_count"
                    ],
                ),
            )

            table.setItem(
                row,
                5,
                NumericItem(
                    provider[
                        "buyer_coverage_pct"
                    ],
                    pct(
                        provider[
                            "buyer_coverage_pct"
                        ]
                    ),
                ),
            )

        for row, provider in enumerate(providers):
            table.setItem(row, 6, NumericItem(provider["clients"]))

        table.setSortingEnabled(
            True
        )

        table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.Stretch,
        )

        return table


# ============================================================
# DASHBOARD
# ============================================================

class DashboardWindow(QMainWindow):

    def __init__(
        self,
        data,
    ):
        super().__init__()

        self.data = data

        self.setWindowTitle(
            "SHES Control · Preventa"
        )

        self.resize(
            1350,
            850,
        )

        central = QWidget()

        self.setCentralWidget(
            central
        )

        layout = QVBoxLayout(
            central
        )

        layout.setContentsMargins(
            20,
            18,
            20,
            18,
        )

        title = QLabel(
            "Dashboard de preventa"
        )

        title.setStyleSheet(
            """
            font-size: 29px;
            font-weight: 700;
            """
        )

        subtitle = QLabel(
            "Preventa procesada · "
            f"{data['preventa_date']} · "
            "Números preliminares hasta "
            "cargar liquidaciones"
        )
        if data.get("week_id"):
            subtitle.setText(
                f"Semana {data['week_id']} · {data['status']} · Datos hasta: {data.get('data_until') or 'sin pedidos'}"
                " · Preventa: importes finales y premios aún no calculados"
            )

        subtitle.setStyleSheet(
            """
            color: #777777;
            """
        )

        layout.addWidget(
            title
        )

        layout.addWidget(
            subtitle
        )

        if data.get("warnings"):
            layout.addWidget(AlertsWidget(data["warnings"]))

        tabs = QTabWidget()

        tabs.addTab(
            self.create_summary_tab(),
            "Resumen",
        )

        tabs.addTab(
            self.create_sellers_tab(),
            "Vendedores",
        )

        tabs.addTab(
            self.create_articles_tab(),
            "Artículos",
        )

        tabs.addTab(
            self.create_providers_tab(),
            "Proveedores",
        )

        layout.addWidget(
            tabs,
            1,
        )

    # ========================================================
    # RESUMEN
    # ========================================================

    def create_summary_tab(
        self,
    ):
        widget = QWidget()

        layout = QVBoxLayout(
            widget
        )

        company = self.data[
            "company"
        ]

        row1 = QHBoxLayout()

        row1.addWidget(
            MetricCard(
                "Venta",
                money(
                    company[
                        "sale"
                    ]
                ),
            )
        )

        row1.addWidget(
            MetricCard(
                "Clientes con venta",
                str(
                    company[
                        "buyers"
                    ]
                ),
            )
        )

        row1.addWidget(
            MetricCard(
                "Ticket promedio",
                money(
                    company[
                        "average_ticket"
                    ]
                ),
            )
        )

        row1.addWidget(
            MetricCard(
                "Cobertura registrada",
                pct(
                    company[
                        "coverage_pct"
                    ]
                ),
            )
        )

        row1.addWidget(
            MetricCard(
                "Conversión",
                pct(
                    company[
                        "conversion_pct"
                    ]
                ),
            )
        )

        layout.addLayout(
            row1
        )

        metrics = QGridLayout()
        for index, (label, key) in enumerate([
            ("Vendedores incluidos", "included_sellers"),
            ("Vendedores excluidos", "excluded_sellers"),
            ("Clientes asignados", "assigned_clients"),
            ("Visitados registrados", "visited_clients"),
            ("No visitados", "not_visited_clients"),
            ("Aprovechamiento %", "portfolio_use_pct"),
            ("Pedidos lógicos", "logical_orders"),
            ("Mix artículos/cliente", "average_article_mix"),
        ]):
            metrics.addWidget(MetricCard(label, str(company[key])), index // 4, index % 4)
        layout.addLayout(metrics)

        controls = QHBoxLayout()

        controls.addWidget(
            QLabel(
                "Comparar vendedores por:"
            )
        )

        self.metric_combo = QComboBox()

        self.metric_combo.addItem(
            "Venta",
            "sale",
        )

        self.metric_combo.addItem(
            "Cobertura",
            "coverage_pct",
        )

        self.metric_combo.addItem(
            "Conversión",
            "conversion_pct",
        )

        self.metric_combo.addItem(
            "Ticket promedio",
            "average_ticket",
        )

        self.metric_combo.addItem(
            "Clientes con venta",
            "buyers",
        )

        self.metric_combo.currentIndexChanged.connect(
            self.update_seller_chart
        )

        controls.addWidget(
            self.metric_combo
        )

        controls.addStretch()

        layout.addLayout(
            controls
        )

        self.seller_chart = BarChart()

        layout.addWidget(
            self.seller_chart
        )

        self.update_seller_chart()

        return widget

    def update_seller_chart(
        self,
    ):
        key = (
            self.metric_combo.currentData()
        )

        data = [
            (
                seller["seller"],
                seller[key],
            )
            for seller in self.data[
                "sellers"
            ]
        ]

        data.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        self.seller_chart.set_data(
            data
        )

    # ========================================================
    # VENDEDORES
    # ========================================================

    def create_sellers_tab(
        self,
    ):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        headers = [
            "Vendedor",
            "Venta",
            "% Empresa",
            "Asignados",
            "Visitados",
            "No visitados",
            "Con venta",
            "Cobertura",
            "Aprovechamiento",
            "Conversión",
            "Ticket",
            "Pedidos",
            "Mix art./cliente",
        ]

        table.setColumnCount(
            len(
                headers
            )
        )

        table.setHorizontalHeaderLabels(
            headers
        )

        sellers = self.data[
            "sellers"
        ]

        table.setRowCount(
            len(
                sellers
            )
        )

        for row, seller in enumerate(
            sellers
        ):

            values = [
                QTableWidgetItem(
                    seller["seller"]
                ),

                NumericItem(
                    seller["sale"],
                    money(
                        seller["sale"]
                    ),
                ),

                NumericItem(
                    seller[
                        "company_share_pct"
                    ],
                    pct(
                        seller[
                            "company_share_pct"
                        ]
                    ),
                ),

                NumericItem(
                    seller[
                        "assigned_clients"
                    ]
                ),

                NumericItem(
                    seller[
                        "visited_clients"
                    ]
                ),

                NumericItem(
                    seller[
                        "not_visited_clients"
                    ]
                ),

                NumericItem(
                    seller[
                        "buyers"
                    ]
                ),

                NumericItem(
                    seller[
                        "coverage_pct"
                    ],
                    pct(
                        seller[
                            "coverage_pct"
                        ]
                    ),
                ),

                NumericItem(
                    seller[
                        "portfolio_use_pct"
                    ],
                    pct(
                        seller[
                            "portfolio_use_pct"
                        ]
                    ),
                ),

                NumericItem(
                    seller[
                        "conversion_pct"
                    ],
                    pct(
                        seller[
                            "conversion_pct"
                        ]
                    ),
                ),

                NumericItem(
                    seller[
                        "average_ticket"
                    ],
                    money(
                        seller[
                            "average_ticket"
                        ]
                    ),
                ),

                NumericItem(
                    seller[
                        "logical_orders"
                    ]
                ),

                NumericItem(
                    seller[
                        "average_article_mix"
                    ],
                    number(
                        seller[
                            "average_article_mix"
                        ]
                    ),
                ),
            ]

            for column, item in enumerate(
                values
            ):
                table.setItem(
                    row,
                    column,
                    item,
                )

        table.setSortingEnabled(
            True
        )

        table.setAlternatingRowColors(
            True
        )

        table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.Stretch,
        )

        table.cellDoubleClicked.connect(
            lambda row, _:
            self.open_seller(
                table.item(
                    row,
                    0,
                ).text()
            )
        )

        return table

    def open_seller(
        self,
        seller_name,
    ):
        seller = next(
            (
                seller
                for seller in self.data[
                    "sellers"
                ]
                if seller[
                    "seller"
                ]
                == seller_name
            ),
            None,
        )

        if not seller:
            return

        dialog = SellerDetailDialog(
            seller,
            self,
        )

        dialog.exec()

    # ========================================================
    # ARTÍCULOS
    # ========================================================

    def create_articles_tab(
        self,
    ):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        headers = [
            "Código",
            "Artículo",
            "Proveedor",
            "Bultos",
            "Venta",
            "Clientes",
            "% Venta empresa",
            "Cobertura compradores",
        ]

        table.setColumnCount(
            len(headers)
        )

        table.setHorizontalHeaderLabels(
            headers
        )

        articles = self.data[
            "articles"
        ]

        table.setRowCount(
            len(
                articles
            )
        )

        for row, article in enumerate(
            articles
        ):

            values = [
                QTableWidgetItem(
                    article["code"]
                ),

                QTableWidgetItem(
                    article["name"]
                ),

                QTableWidgetItem(
                    article["provider"]
                ),

                NumericItem(
                    article["quantity"],
                    number(
                        article[
                            "quantity"
                        ]
                    ),
                ),

                NumericItem(
                    article["sale"],
                    money(
                        article[
                            "sale"
                        ]
                    ),
                ),

                NumericItem(
                    article["clients"]
                ),

                NumericItem(
                    article[
                        "sale_share_pct"
                    ],
                    pct(
                        article[
                            "sale_share_pct"
                        ]
                    ),
                ),

                NumericItem(
                    article[
                        "buyer_coverage_pct"
                    ],
                    pct(
                        article[
                            "buyer_coverage_pct"
                        ]
                    ),
                ),
            ]

            for column, item in enumerate(
                values
            ):
                table.setItem(
                    row,
                    column,
                    item,
                )

        table.setSortingEnabled(
            True
        )

        table.setAlternatingRowColors(
            True
        )

        table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.Stretch,
        )

        return table

    # ========================================================
    # PROVEEDORES
    # ========================================================

    def create_providers_tab(
        self,
    ):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        headers = [
            "Proveedor",
            "Venta",
            "% Venta empresa",
            "Bultos",
            "Artículos distintos",
            "Clientes",
            "Cobertura compradores",
        ]

        table.setColumnCount(
            len(headers)
        )

        table.setHorizontalHeaderLabels(
            headers
        )

        providers = self.data[
            "providers"
        ]

        table.setRowCount(
            len(
                providers
            )
        )

        for row, provider in enumerate(
            providers
        ):

            values = [
                QTableWidgetItem(
                    provider[
                        "provider"
                    ]
                ),

                NumericItem(
                    provider["sale"],
                    money(
                        provider[
                            "sale"
                        ]
                    ),
                ),

                NumericItem(
                    provider[
                        "sale_share_pct"
                    ],
                    pct(
                        provider[
                            "sale_share_pct"
                        ]
                    ),
                ),

                NumericItem(
                    provider[
                        "quantity"
                    ],
                    number(
                        provider[
                            "quantity"
                        ]
                    ),
                ),

                NumericItem(
                    provider[
                        "article_count"
                    ]
                ),

                NumericItem(
                    provider[
                        "clients"
                    ]
                ),

                NumericItem(
                    provider[
                        "buyer_coverage_pct"
                    ],
                    pct(
                        provider[
                            "buyer_coverage_pct"
                        ]
                    ),
                ),
            ]

            for column, item in enumerate(
                values
            ):
                table.setItem(
                    row,
                    column,
                    item,
                )

        table.setSortingEnabled(
            True
        )

        table.setAlternatingRowColors(
            True
        )

        table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.Stretch,
        )

        return table
