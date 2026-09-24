"""Selector y centro semanal. Las reglas comerciales residen en WeekService."""
import json
from pathlib import Path

from app.week_calendar import BRANCHES, as_date, calendar_weeks
from app.week_imports import inspect_batch
from app.week_service import WeekService
from app.week_store import file_hash
from app.review_window import ReviewWindow
from app.dashboard_window import DashboardWindow, NumericItem, money
from app.alerts_widget import AlertsWidget
from app.theme import brand_header
from app.tables import configure_table, capture_tables, restore_tables
from app.review_data import normalize_seller

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QHBoxLayout, QGridLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


def date_edit(value):
    value = as_date(value)
    widget = QDateEdit(QDate(value.year, value.month, value.day))
    widget.setDisplayFormat("dd/MM/yyyy")
    widget.setCalendarPopup(True)
    return widget


def table(headers, rows):
    widget = QTableWidget(len(rows), len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.NoEditTriggers)
    widget.setSelectionBehavior(QTableWidget.SelectRows)
    for row, values in enumerate(rows):
        for col, value in enumerate(values):
            item = NumericItem(value) if isinstance(value, (int, float)) else QTableWidgetItem(str(value))
            widget.setItem(row, col, item)
    configure_table(widget)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().setVisible(False)
    widget.setSortingEnabled(True)
    return widget


def filterable(widget):
    container = QWidget()
    layout = QVBoxLayout(container)
    search = QLineEdit()
    search.setPlaceholderText("Filtrar filas…")
    def apply_filter():
        needle = search.text().casefold()
        for row in range(widget.rowCount()):
            content = " ".join(widget.item(row, c).text() for c in range(widget.columnCount()) if widget.item(row, c))
            widget.setRowHidden(row, needle not in content.casefold())
    search.textChanged.connect(apply_filter)
    widget.horizontalHeader().sortIndicatorChanged.connect(lambda *_: apply_filter())
    layout.addWidget(search)
    layout.addWidget(widget)
    return container


class UploadDialog(QDialog):
    def __init__(self, service, key, paths, parent=None):
        super().__init__(parent)
        self.service, self.key = service, key
        self.candidates = inspect_batch(paths)
        self.revision = service.store.week(key)["revision"]
        week = service.store.week(key)
        self.setWindowTitle("Revisar archivos antes de guardar")
        self.resize(1250, 600)
        layout = QVBoxLayout(self)
        description = QLabel(f"Semana: {week['start_date']} al {week['end_date']}. Pedidos por FECHA ENTREGA. "
                             "Podés cargar todas las partes de CHESS: se combinan por número de pedido y la última carga actualiza los repetidos. "
                             "PorCliente reemplaza al anterior. SIGO: sábado anterior a viernes; un Excel por sucursal. Elegí la sucursal de cada Puntos.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.grid = QTableWidget(len(self.candidates), 8)
        self.grid.setHorizontalHeaderLabels(["Importar", "Archivo / detección", "Tipo", "Sucursal",
                                             "Desde", "Hasta", "Fecha usada", "Resultado previsto"])
        self.controls = []
        seen = set()
        active = {u["logical_key"]: u for u in service.store.uploads(key, active=True)}
        for row, candidate in enumerate(self.candidates):
            prior_duplicate = service.store.duplicate(candidate.hash, key) if candidate.hash else None
            duplicate = bool(candidate.hash and (candidate.hash in seen or prior_duplicate))
            duplicate_message = (f"Ya cargado en esta semana: #{prior_duplicate['id']} · {prior_duplicate['original_filename']}"
                                 if prior_duplicate else "El mismo archivo está repetido en esta selección")
            seen.add(candidate.hash)
            check = QCheckBox()
            check.setChecked(not candidate.error and not duplicate)
            check.setEnabled(not candidate.error and not duplicate)
            self.grid.setCellWidget(row, 0, check)
            detected = f"{candidate.detected_start or '?'} → {candidate.detected_end or '?'}"
            item = QTableWidgetItem(f"{candidate.path.name}\nDetectado: {detected}")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.grid.setItem(row, 1, item)
            self.grid.setItem(row, 2, QTableWidgetItem(candidate.kind))
            branch = QComboBox()
            branch.addItem("Elegir…", "")
            for value in BRANCHES:
                branch.addItem(value.title(), value)
            branch.setEnabled(candidate.kind == "puntos")
            self.grid.setCellWidget(row, 3, branch)
            start = candidate.coverage_start if candidate.kind in {"puntos", "porcliente"} else week["start_date"]
            end = candidate.coverage_end if candidate.kind in {"puntos", "porcliente"} else week["end_date"]
            starts, ends = date_edit(start or week["start_date"]), date_edit(end or week["end_date"])
            starts.setEnabled(False)
            ends.setEnabled(False)
            self.grid.setCellWidget(row, 4, starts)
            self.grid.setCellWidget(row, 5, ends)
            mode = QComboBox()
            mode.addItem("Fecha de entrega", "delivery")
            mode.setEnabled(False)
            self.grid.setCellWidget(row, 6, mode)
            status = QLabel(candidate.error or (duplicate_message if duplicate else "Nuevo"))
            status.setWordWrap(True)
            self.grid.setCellWidget(row, 7, status)
            def update_preview(*_, c=candidate, b=branch, a=starts, z=ends, label=status, dup=duplicate):
                if c.error or dup:
                    return
                if c.kind == "pedidos":
                    label.setText("Se agrega a los pedidos de la semana; los números repetidos se actualizan")
                    return
                logical_key = f"puntos:semanal:{b.currentData()}" if c.kind == "puntos" else c.kind
                prior = active.get(logical_key)
                label.setText("Nuevo" if not prior else f"NUEVA VERSIÓN DISPONIBLE (activa v{prior['version']} conservada)")
            branch.currentIndexChanged.connect(update_preview)
            starts.dateChanged.connect(update_preview)
            ends.dateChanged.connect(update_preview)
            update_preview()
            self.controls.append((check, branch, starts, ends, mode, duplicate))
        self.grid.setEditTriggers(QTableWidget.NoEditTriggers)
        configure_table(self.grid, sortable=False)
        self.grid.resizeRowsToContents()
        layout.addWidget(self.grid)
        for column in (4, 5, 6):
            self.grid.setColumnHidden(column, True)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def commit(self):
        selected = []
        for candidate, (check, branch, start, end, mode, duplicate) in zip(self.candidates, self.controls):
            if not check.isChecked() and not duplicate:
                continue
            candidate.branch = branch.currentData()
            candidate.coverage_start = start.date().toString("yyyy-MM-dd")
            candidate.coverage_end = end.date().toString("yyyy-MM-dd")
            candidate.metadata.update(coverage_confirmed=True, date_mode="delivery")
            selected.append(candidate)
        if not selected:
            QMessageBox.warning(self, "Sin archivos", "Seleccioná al menos un archivo válido")
            return
        try:
            results = self.service.store.commit_uploads(self.key, selected, self.revision)
        except Exception as error:
            QMessageBox.warning(self, "Revisar carga", str(error))
            return
        QMessageBox.information(self, "Carga guardada", "\n".join(f"{r['name']}: {r.get('detail', r['status'])}" for r in results))
        self.accept()


class WeeksWindow(QMainWindow):
    def __init__(self, service=None):
        super().__init__()
        self.service = service or WeekService()
        self.controls = []
        self.service.store.scan_legacy()
        self.setWindowTitle("SHES Control · Semanas")
        self.resize(1100, 740)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(brand_header("Tu semana, en un solo lugar", "Elegí la semana de reparto. Cargá SIGO, Pedidos y PorCliente; después revisá los resultados."))
        self.week_table = table(["Semana", "Estado", "Venta parcial / cierre", "Datos hasta", "Historial anterior"], [])
        layout.addWidget(self.week_table)
        self.week_table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        actions = QHBoxLayout()
        open_button = QPushButton("ENTRAR A LA SEMANA")
        open_button.clicked.connect(self.open_selected)
        actions.addWidget(open_button)
        self.calendar = date_edit(self.service.now())
        actions.addWidget(self.calendar)
        locate = QPushButton("Ir a la semana de esta fecha")
        locate.clicked.connect(self.open_calendar)
        actions.addWidget(locate)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        saved_tables = capture_tables(self)
        for monday in calendar_weeks(self.service.now()):
            self.service.store.ensure_week(monday)
        rows = self.service.store.query("SELECT * FROM weeks ORDER BY start_date DESC")
        self.week_table.setSortingEnabled(False)
        self.week_table.setRowCount(len(rows))
        for index, week in enumerate(rows):
            snapshots = self.service.store.snapshots(week["id"])
            latest = snapshots[0] if snapshots else None
            data = json.loads(Path(latest["file_path"]).read_text(encoding="utf-8")) if latest else {}
            stale = latest and (latest["source_revision"] != week["revision"] or
                                (week["status"] != "CERRADA" and data.get("calculation_version") != 3))
            legacy = self.service.store.query("SELECT COUNT(*) AS n FROM legacy_loads WHERE week_id=?", (week["id"],))[0]["n"]
            values = [f"{week['start_date']} – {week['end_date']}", self.service.progress(week["id"])["status"],
                      ("Actualizar resultados" if stale else money(data["company"]["sale"])) if data else "Sin procesar",
                      data.get("data_until") or "—", f"{legacy} cargas" if legacy else "—"]
            for col, value in enumerate(values):
                item = NumericItem(data["company"]["sale"], value) if col == 2 and data and not stale else QTableWidgetItem(value)
                item.setData(Qt.UserRole, week["id"])
                self.week_table.setItem(index, col, item)
        configure_table(self.week_table)
        restore_tables(self, saved_tables)

    def open_selected(self):
        row = self.week_table.currentRow()
        if row >= 0:
            self.open_week(self.week_table.item(row, 0).data(Qt.UserRole))

    def open_calendar(self):
        week = self.service.store.ensure_week(self.calendar.date().toPython())
        self.refresh()
        self.open_week(week["id"])

    def open_week(self, key):
        window = WeekControlWindow(self.service, key)
        self.controls.append(window)
        window.show()


class WeekControlWindow(QMainWindow):
    def __init__(self, service, key):
        super().__init__()
        self.service, self.key = service, key
        self.child_windows = []
        self.dashboard_support = None
        self.setWindowTitle(f"SHES Control · Centro semanal {key}")
        self.resize(1350, 850)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(brand_header("Control semanal", "1 · SIGO de ambas sucursales     2 · Todas las partes de Pedidos     3 · PorCliente completo"))
        self.title = QLabel()
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        actions = QGridLayout()
        self.upload_button = QPushButton("+ SUBIR ARCHIVOS")
        self.upload_button.clicked.connect(self.upload)
        self.review_button = QPushButton("REVISAR ASIGNACIONES")
        self.review_button.clicked.connect(self.review)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close_or_reopen)
        for button in [self.upload_button, self.review_button]:
            actions.addWidget(button, actions.count() // 4, actions.count() % 4)
        for text, action in [("¿QUÉ ME FALTA?", self.missing), ("VER DASHBOARD", self.dashboard),
                             ("ACTUALIZAR SEMANA", self.recalculate), ("EXPORTAR JSON", self.export)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            actions.addWidget(button, actions.count() // 4, actions.count() % 4)
        actions.addWidget(self.close_button, actions.count() // 4, actions.count() % 4)
        layout.addLayout(actions)
        defaults = QPushButton("Vendedores excluidos por defecto…")
        defaults.setObjectName("secondary")
        defaults.clicked.connect(self.edit_defaults)
        layout.addWidget(defaults)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.refresh()

    def edit_defaults(self):
        current = "\n".join(sorted(self.service.store.default_exclusions()))
        text, ok = QInputDialog.getMultiLineText(self, "Exclusiones editables",
            "Un vendedor por línea. Borrá un nombre para incluirlo por defecto.\n"
            "Se aplica a semanas sin revisión confirmada; las revisadas se cambian en Revisión.", current)
        if ok:
            self.service.store.set_default_exclusions([normalize_seller(n) for n in text.splitlines() if n.strip()])
            self.refresh()

    def guarded(self, action):
        try:
            return action()
        except Exception as error:
            QMessageBox.warning(self, "No se pudo completar", str(error))
            return None

    def refresh(self):
        saved_tables = capture_tables(self)
        selected_tab = self.tabs.currentIndex()
        progress = self.service.progress(self.key)
        self.closed = progress["status"] == "CERRADA"
        self.upload_button.setEnabled(not self.closed)
        self.review_button.setEnabled(not self.closed)
        self.close_button.setText("REABRIR SEMANA" if self.closed else "CERRAR SEMANA")
        try:
            self.data = self.service.metrics(self.key)
        except Exception as error:
            self.review_button.setEnabled(False)
            self.title.setText(f"Semana {self.key}: revisar archivos antes de calcular")
            while self.tabs.count():
                widget = self.tabs.widget(0)
                self.tabs.removeTab(0)
                widget.deleteLater()
            message = QPlainTextEdit(str(error))
            message.setReadOnly(True)
            self.tabs.addTab(message, "Revisar archivos")
            self.tabs.addTab(self.audit_tab(), "Archivos / Auditoría")
            return
        week = progress["week"]
        self.title.setText(f"CENTRO DE CONTROL · {week['start_date']} – {week['end_date']} · {progress['status']}"
                           + (" · SOLO LECTURA OPERATIVA" if self.closed else ""))
        self.upload_button.setEnabled(not self.closed)
        self.review_button.setEnabled(not self.closed)
        self.close_button.setText("REABRIR SEMANA" if self.closed else "CERRAR SEMANA")
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        if self.dashboard_support:
            self.dashboard_support.deleteLater()
        self.dashboard_support = DashboardWindow(self.data)
        summary = QWidget()
        layout = QVBoxLayout(summary)
        company = self.data["company"]
        layout.addWidget(QLabel(f"AVANCE SEMANAL · Ventas hasta: {self.data.get('data_until') or 'sin pedidos'} · "
                               f"Artículos hasta: {self.data.get('articles_until') or 'sin PorCliente'}\n"
                               f"Preventa completa hasta: {self.data.get('complete_until') or 'todavía incompleta'}\n"
                               f"Venta bruta antes de IVA: {money(company.get('sale_gross') or 0)} · "
                               f"Devoluciones: {money(company.get('returns') or 0)} · Venta neta: {money(company.get('sale_net') or 0)}\n"
                               f"Jornadas operativas: {company.get('working_days', 0)} · Clientes compradores netos: {company['buyers']}\n"
                               f"Promedio operativo: {money(company.get('average_daily_sale', 0))}. Comisión y premios usan la venta neta."))
        basis = QLabel(self.data.get("metric_basis", ""))
        basis.setWordWrap(True)
        layout.addWidget(basis)
        layout.addWidget(AlertsWidget(self.data.get("warnings", [])))
        layout.addWidget(self.dashboard_support.create_summary_tab())
        self.tabs.addTab(summary, "Resumen")
        self.tabs.addTab(self.loads_tab(progress), "Cargas")
        sellers = self.dashboard_support.create_sellers_tab()
        # Información operativa por vendedor, sin alterar el contrato del dashboard diario.
        old_columns = sellers.columnCount()
        sellers.setSortingEnabled(False)
        sellers.setColumnCount(old_columns + 5)
        for offset, heading in enumerate(["Venta bruta neta IVA", "Devoluciones", "Venta neta", "Días operativos", "Promedio operativo"]):
            sellers.setHorizontalHeaderItem(old_columns + offset, QTableWidgetItem(heading))
        by_name = {s["seller"]: s for s in self.data["sellers"]}
        for row in range(sellers.rowCount()):
            metrics = by_name[sellers.item(row, 0).text()]
            sellers.setItem(row, old_columns, NumericItem(metrics.get("sale_gross") or 0, money(metrics.get("sale_gross") or 0)))
            sellers.setItem(row, old_columns + 1, NumericItem(metrics.get("returns") or 0, money(metrics.get("returns") or 0)))
            sellers.setItem(row, old_columns + 2, NumericItem(metrics.get("sale_net") or 0, money(metrics.get("sale_net") or 0)))
            sellers.setItem(row, old_columns + 3, NumericItem(metrics.get("working_days", 0)))
            sellers.setItem(row, old_columns + 4, NumericItem(metrics.get("average_daily_sale", 0), money(metrics.get("average_daily_sale", 0))))
        configure_table(sellers)
        sellers.sortItems(1, Qt.DescendingOrder)
        self.tabs.addTab(filterable(sellers), "Vendedores")
        articles_table = self.dashboard_support.create_articles_tab()
        self.add_net_columns(articles_table, self.data["articles"], lambda item: (item["code"], item["provider"]), (0, 2), True)
        articles_table.sortItems(4, Qt.DescendingOrder)
        articles_table.cellDoubleClicked.connect(lambda row, _: self.open_breakdown(
            "articles", articles_table.item(row, 0).text(), articles_table.item(row, 2).text()))
        self.tabs.addTab(filterable(articles_table), "Artículos")
        providers_table = self.dashboard_support.create_providers_tab()
        self.add_net_columns(providers_table, self.data["providers"], lambda item: item["provider"], (0,), False)
        providers_table.sortItems(1, Qt.DescendingOrder)
        providers_table.cellDoubleClicked.connect(lambda row, _: self.open_breakdown(
            "providers", providers_table.item(row, 0).text()))
        self.tabs.addTab(filterable(providers_table), "Proveedores")
        self.tabs.addTab(self.returns_tab(), "Devoluciones")
        from app.reward_window import RewardsPanel
        self.tabs.addTab(RewardsPanel(self.service, self.key, self.data, self), "Premios")
        self.tabs.addTab(self.audit_tab(), "Archivos / Auditoría")
        self.tabs.setCurrentIndex(max(0, selected_tab))
        restore_tables(self, saved_tables)

    def add_net_columns(self, grid, records, key_fn, key_columns, articles):
        by_key = {key_fn(item): item for item in records}
        start = grid.columnCount()
        headings = (["Venta bruta", "Devoluciones", "Venta neta", "Bultos brutos", "Bultos devueltos", "Bultos netos"]
                    if articles else ["Venta bruta", "Devoluciones", "Venta neta"])
        grid.setSortingEnabled(False)
        grid.setColumnCount(start + len(headings))
        for offset, heading in enumerate(headings):
            grid.setHorizontalHeaderItem(start + offset, QTableWidgetItem(heading))
        for row in range(grid.rowCount()):
            parts = tuple(grid.item(row, col).text() for col in key_columns)
            record = by_key.get(parts if len(parts) > 1 else parts[0], {})
            values = [record.get("sale_gross", 0), record.get("returns", 0), record.get("sale_net", 0)]
            if articles:
                values += [record.get("quantity_gross", 0), record.get("quantity_returned", 0), record.get("quantity", 0)]
            for offset, value in enumerate(values):
                grid.setItem(row, start + offset, NumericItem(value or 0, money(value or 0) if offset < 3 else str(round(value or 0, 4))))
        configure_table(grid)

    def loads_tab(self, progress):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("CONTROL DE CARGA · SIGO se muestra en su fecha de preventa; Pedidos y PorCliente, en su fecha de reparto."))
        rows = [[d["name"] + " " + d["date"], d["presale_date"] or "No aplica", d["branches"]["corrientes"], d["branches"]["resistencia"],
                 "CARGADO" if d["reports"]["pedidos"] else "—", "CARGADO" if d["reports"]["porcliente"] else "—",
                 d["state"]] for d in progress["days"]]
        checklist = table(["Reparto", "Preventa SIGO", "Corrientes", "Resistencia", "Pedidos", "PorCliente", "Estado"], rows)
        checklist.setSortingEnabled(False)
        # La tabla puede ordenarse, pero se abre en orden calendario, no alfabético.
        for row in range(checklist.rowCount()):
            text = checklist.item(row, 0).text()
            ordinal = as_date(text[-10:]).toordinal()
            checklist.setItem(row, 0, NumericItem(ordinal, text))
        checklist.setSortingEnabled(True)
        checklist.sortItems(0, Qt.AscendingOrder)
        layout.addWidget(checklist)
        daily = self.data.get("daily_totals", []) + self.data.get("daily_activity", [])
        detail = table(["Vendedor", "Preventa", "Reparto", "Cartera", "Visitados", "Vendidos SIGO"],
            [[r["seller"], r["presale_date"], r["delivery_date"], r["assigned"], r["visited"], r["sold_sigo"]] for r in daily])
        layout.addWidget(QLabel("Actividad por vendedor y día · Vendidos SIGO cuenta clientes con Hora Venta, sin inventar importes."))
        layout.addWidget(filterable(detail))
        parts = sum(u["type"] == "pedidos" for u in self.service.store.uploads(self.key, active=True))
        layout.addWidget(QLabel(f"Pedidos: {parts} archivo(s) activos. Se combinan por número y fecha de entrega dentro de esta semana."))
        actions = QHBoxLayout()
        self.work_date = date_edit(progress["week"]["start_date"])
        self.work_branch = QComboBox()
        self.work_branch.addItems(["Corrientes y Resistencia", "Corrientes", "Resistencia"])
        actions.addWidget(self.work_date)
        actions.addWidget(self.work_branch)
        for text, worked in [("NO SE TRABAJÓ", False), ("REVERTIR NO TRABAJADO", True)]:
            button = QPushButton(text)
            button.setEnabled(not self.closed)
            button.clicked.connect(lambda _, value=worked: self.mark_worked(value))
            actions.addWidget(button)
        layout.addLayout(actions)
        return widget

    def open_breakdown(self, kind, name, provider=None):
        rows = []
        for seller in self.data["sellers"]:
            for item in seller[kind]:
                matches = item["provider"] == name if kind == "providers" else (
                    item["code"] == name and item["provider"] == provider)
                if matches:
                    rows.append([seller["seller"], item["sale"], item["quantity"], item["clients"], item["buyer_coverage_pct"]])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{name} · detalle por vendedor")
        dialog.resize(850, 550)
        layout = QVBoxLayout(dialog)
        layout.addWidget(filterable(table(["Vendedor", "Venta", "Bultos", "Clientes", "Cobertura %"], rows)))
        dialog.exec()

    def mark_worked(self, worked):
        reason, ok = QInputDialog.getText(self, "Jornada", "Motivo opcional:")
        if not ok:
            return
        selected = self.work_branch.currentIndex()
        branches = BRANCHES if selected == 0 else (BRANCHES[selected - 1],)
        self.guarded(lambda: self.service.store.set_worked(self.key, self.work_date.date().toPython(), branches, worked, reason))
        self.refresh()

    def returns_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Los negativos con match descuentan automáticamente. Solo los negativos sin match dentro de la semana requieren decisión. "
                               "Los anteriores o posteriores sin una venta semanal compatible se ignoran."))
        self.return_filter = QComboBox()
        self.return_filter.addItems(["Todas", "Con match", "Sin match", "Aprobadas", "Rechazadas", "Pendientes"])
        layout.addWidget(self.return_filter)
        self.return_rows = self.data.get("returns", [])
        self.return_table = table(["Huella", "Fecha", "Cliente", "Vendedor origen", "Vendedor final", "Artículo", "Proveedor",
                                   "Cantidad", "Importe", "Match", "Decisión", "Impacto", "Advertencia"],
            [[r["fingerprint"], r["date"], r["client"], r["source_seller"], r["assigned_seller"], r["article"], r["provider"],
              r["quantity"], r["amount_net"], "Sí" if r["matched"] else "No", r["decision"], r["impact"], r["warning"]]
             for r in self.return_rows])
        self.return_table.setColumnHidden(0, True)
        self.return_table.setSelectionMode(QTableWidget.ExtendedSelection)
        def apply_filter():
            selected = self.return_filter.currentText()
            by_fingerprint = {r["fingerprint"]: r for r in self.return_rows}
            for row in range(self.return_table.rowCount()):
                value = by_fingerprint[self.return_table.item(row, 0).text()]
                visible = (selected == "Todas" or selected == "Con match" and value["matched"] or
                    selected == "Sin match" and not value["matched"] or selected == "Aprobadas" and value["decision"] == "APROBADA" or
                    selected == "Rechazadas" and value["decision"] == "RECHAZADA" or selected == "Pendientes" and value["decision"] == "PENDIENTE")
                self.return_table.setRowHidden(row, not visible)
        self.return_filter.currentTextChanged.connect(apply_filter)
        layout.addWidget(self.return_table)
        actions = QGridLayout()
        for index, (text, decision, all_pending) in enumerate([("APROBAR SELECCIONADAS", "APROBADA", False),
                                            ("RECHAZAR SELECCIONADAS", "RECHAZADA", False),
                                            ("APROBAR TODAS LAS PENDIENTES", "APROBADA", True),
                                            ("RECHAZAR TODAS LAS PENDIENTES", "RECHAZADA", True)]):
            button = QPushButton(text)
            button.setEnabled(not self.closed)
            button.clicked.connect(lambda _, value=decision, all_rows=all_pending: self.decide_returns(value, all_rows))
            actions.addWidget(button, index // 2, index % 2)
        layout.addLayout(actions)
        return widget

    def decide_returns(self, decision, all_pending=False):
        by_fingerprint = {r["fingerprint"]: r for r in self.return_rows}
        if all_pending:
            records = [r for r in self.return_rows if r["decision"] == "PENDIENTE"]
        else:
            records = [by_fingerprint[self.return_table.item(index.row(), 0).text()]
                       for index in self.return_table.selectionModel().selectedRows()
                       if not self.return_table.isRowHidden(index.row())]
            records = [r for r in records if r["decision"] == "PENDIENTE"]
        if not records:
            QMessageBox.information(self, "Devoluciones", "No hay devoluciones pendientes seleccionadas.")
            return
        verb = "aprobar" if decision == "APROBADA" else "rechazar"
        if QMessageBox.question(self, "Devoluciones", f"¿{verb.capitalize()} {len(records)} devoluciones pendientes?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        note, ok = QInputDialog.getText(self, "Devolución", "Nota opcional:")
        if ok:
            self.guarded(lambda: self.service.decide_returns(self.key, [r["fingerprint"] for r in records], decision, note))
            self.refresh()

    def audit_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        uploads = self.service.store.uploads(self.key)
        self.upload_revision = self.service.store.week(self.key)["revision"]
        self.file_table = table(["ID", "Tipo", "Sucursal", "Fechas", "Versión", "Estado", "Nombre", "SHA-256", "Subido"],
            [[u["id"], u["type"], u["branch"] or "—", f"{u['coverage_start']} / {u['coverage_end']}", u["version"],
              "ELIMINADA" if u["removed_at"] else "ACTIVA" if u["active"] else "HISTÓRICA", u["original_filename"], u["hash"], u["uploaded_at"]] for u in uploads])
        self.file_table.setSelectionMode(QTableWidget.ExtendedSelection)
        layout.addWidget(filterable(self.file_table))
        layout.addWidget(QLabel("Seleccioná varias cargas con Ctrl o Shift. Las eliminadas se conservan solo en auditoría."))
        self.remove_uploads_button = QPushButton("Eliminar cargas seleccionadas")
        self.remove_uploads_button.setObjectName("danger")
        self.remove_uploads_button.setEnabled(not self.closed)
        self.remove_uploads_button.clicked.connect(self.remove_selected_uploads)
        layout.addWidget(self.remove_uploads_button)
        activate = QPushButton("Hacer ACTIVA la versión seleccionada")
        activate.setEnabled(not self.closed)
        activate.clicked.connect(self.activate_selected)
        layout.addWidget(activate)
        events = self.service.store.query("SELECT * FROM audit_events WHERE week_id=? ORDER BY id DESC", (self.key,))
        audit = QPlainTextEdit()
        audit.setReadOnly(True)
        audit.setPlainText("\n".join(f"{e['timestamp']} · {e['action']} · {e['details']}" for e in events))
        audit.setMaximumHeight(140)
        layout.addWidget(audit)
        self.history_combo = QComboBox()
        for snapshot in self.service.store.snapshots(self.key):
            self.history_combo.addItem(f"{snapshot['kind']} · {snapshot['created_at']}", snapshot["file_path"])
        legacy = self.service.store.query("SELECT * FROM legacy_loads WHERE week_id=? ORDER BY date,folder", (self.key,))
        for load in legacy:
            path = Path(load["folder"]) / "preventa_procesada.json"
            if path.exists():
                self.history_combo.addItem(f"Historial diario · {load['date']} · {Path(load['folder']).name}", str(path))
        layout.addWidget(QLabel(f"Historial anterior: {len(legacy)} cargas conservadas. No se suman ni se activan automáticamente."))
        legacy_button = QPushButton("Explorar archivos y revisiones del historial diario")
        legacy_button.clicked.connect(self.explore_legacy)
        layout.addWidget(legacy_button)
        layout.addWidget(self.history_combo)
        view = QPushButton("Ver snapshot / dashboard histórico")
        view.clicked.connect(self.view_snapshot)
        layout.addWidget(view)
        return widget

    def explore_legacy(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Historial diario conservado · solo lectura")
        dialog.resize(1000, 650)
        layout = QVBoxLayout(dialog)
        rows = []
        for load in self.service.store.query("SELECT * FROM legacy_loads WHERE week_id=? ORDER BY date,folder", (self.key,)):
            for path in sorted(Path(load["folder"]).iterdir()):
                if path.is_file() and path.suffix.lower() in {".xlsx", ".json"}:
                    rows.append([load["date"], Path(load["folder"]).name, path.name, str(path), file_hash(path)])
        files = table(["Fecha", "Carga", "Archivo", "Ubicación", "SHA-256"], rows)
        layout.addWidget(filterable(files))
        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlaceholderText("Doble clic en un JSON para consultar su revisión o resultado original.")
        layout.addWidget(detail)
        def inspect(row, _):
            path = Path(files.item(row, 3).text())
            if path.suffix == ".json":
                detail.setPlainText(path.read_text(encoding="utf-8"))
        files.cellDoubleClicked.connect(inspect)
        dialog.exec()

    def remove_selected_uploads(self):
        rows = sorted(index.row() for index in self.file_table.selectionModel().selectedRows()
                      if not self.file_table.isRowHidden(index.row()))
        rows = [row for row in rows if self.file_table.item(row, 5).text() != "ELIMINADA"]
        if not rows:
            QMessageBox.information(self, "Eliminar cargas", "Seleccioná cargas que todavía no estén eliminadas.")
            return
        ids = [int(self.file_table.item(row, 0).text()) for row in rows]
        names = "\n".join(f"• #{self.file_table.item(row, 0).text()} · {self.file_table.item(row, 6).text()}" for row in rows)
        message = (f"¿Eliminar estas {len(ids)} cargas de la semana?\n\n{names}\n\n"
                   "Se recalcularán los resultados y habrá que confirmar nuevamente la revisión. "
                   "No se activará una versión anterior automáticamente. Podés volver a subir los mismos Excel. "
                   "Los archivos y resultados históricos se conservan en auditoría.")
        if QMessageBox.question(self, "Eliminar cargas", message, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self.guarded(lambda: self.service.store.remove_uploads(self.key, ids, self.upload_revision))
        self.refresh()
        self.tabs.setCurrentIndex(self.tabs.count() - 1)

    def activate_selected(self):
        row = self.file_table.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Cambiar versión activa", "¿Usar esta versión? Las anteriores se conservan y deberá confirmar nuevamente la revisión.") == QMessageBox.Yes:
            self.guarded(lambda: self.service.store.activate(self.key, int(self.file_table.item(row, 0).text())))
            self.refresh()

    def view_snapshot(self):
        path = self.history_combo.currentData()
        if path:
            def show():
                window = DashboardWindow(json.loads(Path(path).read_text(encoding="utf-8")))
                self.child_windows.append(window)
                window.show()
            self.guarded(show)

    def upload(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar varios Excel", "", "Excel (*.xlsx)")
        if paths:
            dialog = UploadDialog(self.service, self.key, paths, self)
            if dialog.exec() == QDialog.Accepted:
                self.recalculate()

    def review(self):
        def show():
            session, _, _, revision = self.service.build_session(self.key)
            state = {"revision": revision}
            def save(value):
                result = self.service.confirm_review(self.key, value, state["revision"])
                state["revision"] = self.service.store.week(self.key)["revision"]
                self.refresh()
                return result
            def process(_):
                if self.service.store.week(self.key)["revision"] != state["revision"]:
                    raise ValueError("La semana cambió; revisá las nuevas versiones")
                data = self.service.process(self.key)
                self.refresh()
                return data
            window = ReviewWindow(session, save_callback=save, process_callback=process)
            self.child_windows.append(window)
            window.show()
        self.guarded(show)

    def dashboard(self):
        data = self.guarded(lambda: self.service.metrics(self.key))
        if data is not None:
            window = DashboardWindow(data)
            self.child_windows.append(window)
            window.show()

    def recalculate(self):
        self.guarded(lambda: self.service.process(self.key))
        self.refresh()

    def missing(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("¿Qué me falta cargar?")
        dialog.resize(750, 650)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(self.service.missing_explanation(self.key))
        text.setReadOnly(True)
        layout.addWidget(text)
        dialog.exec()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exportar métricas", f"{self.key}.json", "JSON (*.json)")
        if path:
            self.guarded(lambda: self.service.export(self.key, path))

    def close_or_reopen(self):
        if self.closed:
            reason, ok = QInputDialog.getText(self, "Reabrir semana", "Motivo (el cierre original se conserva):")
            if ok:
                self.guarded(lambda: self.service.store.reopen(self.key, reason))
        elif QMessageBox.question(self, "Cerrar semana", "¿Cerrar la semana? Se conservará un snapshot con ventas, devoluciones, comisión y premios.") == QMessageBox.Yes:
            progress = self.service.progress(self.key)
            reason = ""
            if self.service.now().isoformat() <= progress["week"]["end_date"]:
                reason, ok = QInputDialog.getText(self, "Cierre excepcional", "La semana todavía no terminó. Motivo obligatorio:")
                if not ok or not reason.strip():
                    return
            self.guarded(lambda: self.service.close(self.key, reason))
        self.refresh()
