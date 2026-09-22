"""Selector y centro semanal. Las reglas comerciales residen en WeekService."""
import json
from pathlib import Path

from app.week_calendar import BRANCHES, as_date, calendar_weeks
from app.week_imports import inspect_batch, UploadCandidate
from app.week_service import WeekService
from app.week_store import file_hash
from app.review_window import ReviewWindow
from app.dashboard_window import DashboardWindow, NumericItem, money
from app.alerts_widget import AlertsWidget

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
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
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
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
        description = QLabel("Elegí la sucursal de cada Puntos. Para reportes, confirmá el rango COMERCIAL exportado, "
                             "incluidos los días sin ventas. PorCliente conserva su período detectado; indicá si representa alta o entrega.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.grid = QTableWidget(len(self.candidates), 8)
        self.grid.setHorizontalHeaderLabels(["Importar", "Archivo / detección", "Tipo", "Sucursal",
                                             "Desde comercial", "Hasta comercial", "Fechas PorCliente", "Resultado previsto"])
        self.controls = []
        seen = set()
        active = {u["logical_key"]: u for u in service.store.uploads(key, active=True)}
        for row, candidate in enumerate(self.candidates):
            duplicate = bool(candidate.hash and (candidate.hash in seen or service.store.duplicate(candidate.hash)))
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
            start = candidate.coverage_start if candidate.kind == "puntos" else week["start_date"]
            end = candidate.coverage_end if candidate.kind == "puntos" else (
                min(week["end_date"], max(week["start_date"], candidate.detected_end or week["start_date"])))
            starts, ends = date_edit(start or week["start_date"]), date_edit(end or week["end_date"])
            starts.setEnabled(candidate.kind != "puntos")
            ends.setEnabled(candidate.kind != "puntos")
            self.grid.setCellWidget(row, 4, starts)
            self.grid.setCellWidget(row, 5, ends)
            mode = QComboBox()
            mode.addItem("Fecha de entrega", "delivery")
            mode.addItem("Fecha comercial (alta)", "commercial")
            mode.addItem("Acumulado sin fecha diaria", "aggregate")
            mode.setEnabled(candidate.kind == "porcliente")
            self.grid.setCellWidget(row, 6, mode)
            status = QLabel(candidate.error or ("Duplicado exacto: ignorado" if duplicate else "Nuevo"))
            status.setWordWrap(True)
            self.grid.setCellWidget(row, 7, status)
            def update_preview(*_, c=candidate, b=branch, a=starts, z=ends, label=status, dup=duplicate):
                if c.error or dup:
                    return
                logical_key = f"puntos:{a.date().toString('yyyy-MM-dd')}:{b.currentData()}" if c.kind == "puntos" else c.kind
                prior = active.get(logical_key)
                label.setText("Nuevo" if not prior else f"NUEVA VERSIÓN DISPONIBLE (activa v{prior['version']} conservada)")
            branch.currentIndexChanged.connect(update_preview)
            starts.dateChanged.connect(update_preview)
            ends.dateChanged.connect(update_preview)
            update_preview()
            self.controls.append((check, branch, starts, ends, mode, duplicate))
        self.grid.setEditTriggers(QTableWidget.NoEditTriggers)
        self.grid.resizeColumnsToContents()
        self.grid.resizeRowsToContents()
        layout.addWidget(self.grid)
        self.confirm_ranges = QCheckBox("Confirmo que los rangos comerciales indicados corresponden a las exportaciones seleccionadas")
        layout.addWidget(self.confirm_ranges)
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
            candidate.metadata.update(coverage_confirmed=self.confirm_ranges.isChecked(), date_mode=mode.currentData())
            selected.append(candidate)
        if not selected:
            QMessageBox.warning(self, "Sin archivos", "Seleccioná al menos un archivo válido")
            return
        try:
            results = self.service.store.commit_uploads(self.key, selected, self.revision)
        except Exception as error:
            QMessageBox.warning(self, "Revisar carga", str(error))
            return
        QMessageBox.information(self, "Carga guardada", "\n".join(f"{r['name']}: {r['status']}" for r in results))
        self.accept()


class WeeksWindow(QMainWindow):
    def __init__(self, service=None):
        super().__init__()
        self.service = service or WeekService()
        self.controls = []
        self.service.store.scan_legacy()
        self.setWindowTitle("SHES Control · Semanas comerciales")
        self.resize(1100, 740)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("SEMANAS COMERCIALES · lunes a domingo"))
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
        for monday in calendar_weeks(self.service.now()):
            self.service.store.ensure_week(monday)
        rows = self.service.store.query("SELECT * FROM weeks ORDER BY start_date DESC")
        self.week_table.setSortingEnabled(False)
        self.week_table.setRowCount(len(rows))
        for index, week in enumerate(rows):
            snapshots = self.service.store.snapshots(week["id"])
            latest = snapshots[0] if snapshots else None
            data = json.loads(Path(latest["file_path"]).read_text(encoding="utf-8")) if latest else {}
            stale = latest and latest["source_revision"] != week["revision"]
            legacy = self.service.store.query("SELECT COUNT(*) AS n FROM legacy_loads WHERE week_id=?", (week["id"],))[0]["n"]
            values = [f"{week['start_date']} – {week['end_date']}", self.service.progress(week["id"])["status"],
                      ("Actualizar resultados" if stale else money(data["company"]["sale"])) if data else "Sin procesar",
                      data.get("data_until") or "—", f"{legacy} cargas" if legacy else "—"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, week["id"])
                self.week_table.setItem(index, col, item)
        self.week_table.setSortingEnabled(True)

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
        self.title = QLabel()
        layout.addWidget(self.title)
        actions = QHBoxLayout()
        self.upload_button = QPushButton("+ SUBIR ARCHIVOS")
        self.upload_button.clicked.connect(self.upload)
        self.review_button = QPushButton("REVISAR ASIGNACIONES")
        self.review_button.clicked.connect(self.review)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close_or_reopen)
        for button in [self.upload_button, self.review_button]:
            actions.addWidget(button)
        for text, action in [("¿QUÉ ME FALTA?", self.missing), ("VER DASHBOARD", self.dashboard),
                             ("ACTUALIZAR SEMANA", self.recalculate), ("EXPORTAR JSON", self.export)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            actions.addWidget(button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.refresh()

    def guarded(self, action):
        try:
            return action()
        except Exception as error:
            QMessageBox.warning(self, "No se pudo completar", str(error))
            return None

    def refresh(self):
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
        layout.addWidget(QLabel(f"PROGRESO COMERCIAL · Ventas hasta: {self.data.get('data_until') or 'sin pedidos'} · "
                               f"Artículos hasta: {self.data.get('articles_until') or 'sin PorCliente'}\n"
                               f"Preventa completa hasta: {self.data.get('complete_until') or 'todavía incompleta'}\n"
                               f"Venta acumulada: {money(company['sale'])} · Jornadas operativas procesadas: {company.get('working_days', 0)}\n"
                               f"Promedio operativo: {money(company.get('average_daily_sale', 0))} · Clientes compradores: {company['buyers']}\n"
                               "Premios: pendientes de implementación. Importes netos de liquidaciones aún no conciliados."))
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
        sellers.setColumnCount(old_columns + 2)
        sellers.setHorizontalHeaderItem(old_columns, QTableWidgetItem("Días operativos"))
        sellers.setHorizontalHeaderItem(old_columns + 1, QTableWidgetItem("Promedio operativo"))
        by_name = {s["seller"]: s for s in self.data["sellers"]}
        for row in range(sellers.rowCount()):
            metrics = by_name[sellers.item(row, 0).text()]
            sellers.setItem(row, old_columns, NumericItem(metrics.get("working_days", 0)))
            sellers.setItem(row, old_columns + 1, NumericItem(metrics.get("average_daily_sale", 0), money(metrics.get("average_daily_sale", 0))))
        sellers.setSortingEnabled(True)
        sellers.sortItems(1, Qt.DescendingOrder)
        self.tabs.addTab(filterable(sellers), "Vendedores")
        articles_table = self.dashboard_support.create_articles_tab()
        articles_table.sortItems(4, Qt.DescendingOrder)
        articles_table.cellDoubleClicked.connect(lambda row, _: self.open_breakdown(
            "articles", articles_table.item(row, 0).text(), articles_table.item(row, 2).text()))
        self.tabs.addTab(filterable(articles_table), "Artículos")
        providers_table = self.dashboard_support.create_providers_tab()
        providers_table.sortItems(1, Qt.DescendingOrder)
        providers_table.cellDoubleClicked.connect(lambda row, _: self.open_breakdown(
            "providers", providers_table.item(row, 0).text()))
        self.tabs.addTab(filterable(providers_table), "Proveedores")
        self.tabs.addTab(self.liquidations_tab(progress), "Liquidaciones")
        self.tabs.addTab(QLabel("Premios semanales: integración futura. Se conservarán pagos y cierres originales al reabrir."), "Premios")
        self.tabs.addTab(self.audit_tab(), "Archivos / Auditoría")

    def loads_tab(self, progress):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("PROGRESO DOCUMENTAL · La jornada actual y las futuras no se marcan faltantes."))
        rows = [[d["name"] + " " + d["date"], d["branches"]["corrientes"], d["branches"]["resistencia"],
                 "CARGADO" if d["reports"]["pedidos"] else "—", "CARGADO" if d["reports"]["porcliente"] else "—",
                 d["state"]] for d in progress["days"]]
        checklist = table(["Día", "Corrientes", "Resistencia", "Pedidos", "PorCliente", "Estado"], rows)
        checklist.setSortingEnabled(False)
        # La tabla puede ordenarse, pero se abre en orden calendario, no alfabético.
        for row in range(checklist.rowCount()):
            text = checklist.item(row, 0).text()
            ordinal = as_date(text[-10:]).toordinal()
            checklist.setItem(row, 0, NumericItem(ordinal, text))
        checklist.setSortingEnabled(True)
        checklist.sortItems(0, Qt.AscendingOrder)
        layout.addWidget(checklist)
        sunday = self.data.get("sunday", {})
        layout.addWidget(QLabel(f"Domingo: SIGO no aplica · Pedidos excepcionales: {sunday.get('logical_orders', 0)} · Venta: {money(sunday.get('sale', 0))}"))
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

    def liquidations_tab(self, progress):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Archivos adjuntos para auditoría; todavía no se interpretan importes ni devoluciones.\n"
                               "La cantidad esperada de camiones es desconocida. Administración confirma la integridad por jornada."))
        rows = [[d["date"], d["liquidations"]["count_uploaded"],
                 "Confirmadas" if d["liquidations"]["confirmed_complete"] else "Sin confirmar",
                 d["liquidations"]["confirmed_at"] or "—", d["liquidations"]["note"]] for d in progress["days"]]
        layout.addWidget(table(["Jornada comercial", "Cargadas", "Completas", "Confirmación", "Nota"], rows))
        actions = QHBoxLayout()
        self.liq_date = date_edit(progress["week"]["start_date"])
        actions.addWidget(self.liq_date)
        for text, callback in [("Adjuntar liquidaciones", self.attach_liquidations),
                               ("CONFIRMAR LIQUIDACIONES COMPLETAS", self.confirm_liquidations)]:
            button = QPushButton(text)
            button.setEnabled(not self.closed)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        return widget

    def attach_liquidations(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Adjuntar liquidaciones de la jornada", "", "Excel (*.xlsx)")
        if not paths:
            return
        day = self.liq_date.date().toString("yyyy-MM-dd")
        if QMessageBox.question(self, "Confirmar adjuntos", f"¿Guardar {len(paths)} liquidaciones para la jornada comercial {day}?") != QMessageBox.Yes:
            return
        def save():
            candidates = [UploadCandidate(Path(p), file_hash(p), "liquidacion", coverage_start=day, coverage_end=day,
                         metadata={"coverage_confirmed": True, "opaque_attachment": True}) for p in paths]
            self.service.store.commit_uploads(self.key, candidates, self.service.store.week(self.key)["revision"])
        self.guarded(save)
        self.refresh()

    def confirm_liquidations(self):
        note, ok = QInputDialog.getText(self, "Liquidaciones completas", "Confirmo que están todas. Nota (obligatoria si no hubo repartos):")
        if ok:
            self.guarded(lambda: self.service.store.confirm_liquidations(self.key, self.liq_date.date().toPython(), note))
            self.refresh()

    def audit_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        uploads = self.service.store.uploads(self.key)
        self.file_table = table(["ID", "Tipo", "Sucursal", "Rango comercial", "Versión", "Estado", "Nombre", "SHA-256", "Subido"],
            [[u["id"], u["type"], u["branch"] or "—", f"{u['coverage_start']} / {u['coverage_end']}", u["version"],
              "ACTIVA" if u["active"] else "HISTÓRICA", u["original_filename"], u["hash"], u["uploaded_at"]] for u in uploads])
        layout.addWidget(filterable(self.file_table))
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

    def activate_selected(self):
        row = self.file_table.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Cambiar versión activa", "¿Usar esta versión? Las anteriores se conservan y deberá confirmar nuevamente revisión y liquidaciones.") == QMessageBox.Yes:
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
        elif QMessageBox.question(self, "Cerrar semana", "¿Cerrar administrativamente? Se conservará un snapshot. Los premios y la conciliación de importes de liquidaciones aún no están implementados.") == QMessageBox.Yes:
            self.guarded(lambda: self.service.close(self.key))
        self.refresh()
