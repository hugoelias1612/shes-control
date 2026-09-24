"""Configuración, control semanal e historial de premios dentro de la pestaña existente."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QTabWidget, QLineEdit, QTextEdit, QComboBox, QCheckBox, QDoubleSpinBox,
    QSpinBox, QDialogButtonBox, QMessageBox, QListWidget, QListWidgetItem, QFileDialog,
    QProgressBar, QScrollArea)

from app.rewards import RewardService, METRICS, OPERATORS, display, metric_key
from app.reward_export import export_rewards
from app.tables import capture_tables, restore_tables
from app.week_store import file_hash


def widgets():
    # Import tardío: week_window construye esta pestaña al refrescar la semana.
    from app.week_window import table, filterable, date_edit
    return table, filterable, date_edit


def spin(value=0, decimals=2):
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(-999999999999,999999999999)
    box.setGroupSeparatorShown(True)
    box.setValue(value or 0)
    return box


def format_columns(grid, columns):
    for row in range(grid.rowCount()):
        for col, unit in columns.items():
            item = grid.item(row,col)
            if item and hasattr(item,"value"):
                item.setText(display(item.value,unit))


def buttons(dialog, layout, save):
    box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Save).setText("Guardar")
    box.button(QDialogButtonBox.Cancel).setText("Cancelar")
    def commit():
        try:
            save()
        except (ValueError, OSError) as error:
            QMessageBox.warning(dialog,"Revisar datos",str(error))
            return
        dialog.accept()
    box.accepted.connect(commit)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)


class RuleDialog(QDialog):
    def __init__(self, engine, key, metrics, rule=None, duplicate=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicar premio" if duplicate else "Editar premio" if rule else "Crear premio")
        self.resize(650,780)
        self.engine, self.rule = engine, rule or {}
        r = self.rule
        _, _, date_edit = widgets()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Una regla = una métrica. Todos los premios y niveles cumplidos se suman.\nLa vigencia se evalúa por el lunes de la semana, sin prorrateos."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.name = QLineEdit(r.get("name","") + (" (copia)" if duplicate else ""))
        self.description = QTextEdit(r.get("description","")); self.description.setMaximumHeight(70)
        self.metric_combo = QComboBox()
        for key_metric, definition in METRICS.items():
            self.metric_combo.addItem(definition[0],key_metric)
        self.metric_combo.setCurrentIndex(max(0,self.metric_combo.findData(r.get("metric","sale_net"))))
        self.operator = QComboBox(); self.operator.addItems(list(OPERATORS)); self.operator.setCurrentText(r.get("operator",">="))
        self.target = spin(r.get("target",0),4); self.target.setMinimum(0)
        self.amount = spin(r.get("amount",0)); self.amount.setMinimum(0)
        self.group = QLineEdit(r.get("group",""))
        self.level = QSpinBox(); self.level.setRange(-1,9999); self.level.setSpecialValueText("Sin nivel"); self.level.setValue(r.get("level") if r.get("level") is not None else -1)
        self.start = date_edit(r.get("date_from",engine.store.week(key)["start_date"]))
        self.has_end = QCheckBox("Limitar vigencia hasta")
        self.has_end.setChecked(bool(r.get("date_to")))
        self.end = date_edit(r.get("date_to") or engine.store.week(key)["end_date"])
        self.end.setEnabled(self.has_end.isChecked()); self.has_end.toggled.connect(self.end.setEnabled)
        self.provider = QComboBox(); self.provider.setEditable(True); self.provider.addItem("")
        self.provider.addItems(sorted({p["provider"] for s in metrics["sellers"] for p in s["providers"]}))
        self.provider.setCurrentText(r.get("provider",""))
        self.article = QComboBox(); self.article.setEditable(True); self.article.addItem("","")
        article_names = {a["code"]:a["name"] for s in metrics["sellers"] for a in s["articles"]}
        for code,name in sorted(article_names.items()):
            self.article.addItem(f"{code} · {name}",code)
        index = self.article.findData(r.get("article",""))
        if index>=0:self.article.setCurrentIndex(index)
        else:self.article.setCurrentText(r.get("article",""))
        self.manual = QCheckBox("Valor verificado por Administración"); self.manual.setChecked(r.get("manual",False))
        self.active = QCheckBox("Premio activo"); self.active.setChecked(r.get("active",True))
        self.all_sellers = QCheckBox("Todos los vendedores incluidos en la semana"); self.all_sellers.setChecked(not r.get("scope"))
        self.sellers = QListWidget(); self.sellers.setMaximumHeight(145)
        for name in sorted({s["seller"] for s in metrics["sellers"]} | set(r.get("scope",[]))):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in r.get("scope",[]) else Qt.Unchecked)
            self.sellers.addItem(item)
        self.sellers.setEnabled(not self.all_sellers.isChecked())
        self.all_sellers.toggled.connect(lambda checked:self.sellers.setEnabled(not checked))
        self.observation = QTextEdit(r.get("observation","")); self.observation.setMaximumHeight(70)
        for label,field in [("Nombre",self.name),("Descripción",self.description),("Métrica",self.metric_combo),("Operador",self.operator),
            ("Objetivo",self.target),("Premio adicional ($)",self.amount),("Grupo",self.group),("Nivel / orden",self.level),
            ("Desde",self.start),("",self.has_end),("Hasta",self.end),("Proveedor",self.provider),("Código de artículo",self.article),
            ("Control",self.manual),("Estado",self.active),("Alcance",self.all_sellers),("Vendedores",self.sellers),("Observación",self.observation)]:
            form.addRow(label,field)
        def metric_changed():
            source = METRICS[self.metric_combo.currentData()][2]
            self.provider.setEnabled(source in {"provider","article"})
            self.article.setEnabled(source=="article")
            self.manual.setEnabled(source!="manual")
            if source=="manual":self.manual.setChecked(True)
            self.target.setDecimals(0 if METRICS[self.metric_combo.currentData()][1]=="count" else 4)
        self.metric_combo.currentIndexChanged.connect(metric_changed); metric_changed()
        def save():
            scope = [] if self.all_sellers.isChecked() else [self.sellers.item(i).text() for i in range(self.sellers.count()) if self.sellers.item(i).checkState()==Qt.Checked]
            if not self.all_sellers.isChecked() and not scope:
                raise ValueError("Seleccioná al menos un vendedor o elegí Todos")
            payload = dict(name=self.name.text(),description=self.description.toPlainText(),metric=self.metric_combo.currentData(),
                operator=self.operator.currentText(),target=self.target.value(),amount=self.amount.value(),group=self.group.text(),
                level=None if self.level.value()<0 else self.level.value(),provider=self.provider.currentText(),
                article=self.article.currentText().split(" · ")[0],manual=self.manual.isChecked(),active=self.active.isChecked(),
                date_from=self.start.date().toString("yyyy-MM-dd"),date_to=self.end.date().toString("yyyy-MM-dd") if self.has_end.isChecked() else "",
                scope=scope,observation=self.observation.toPlainText())
            self.engine.save_rule(payload,None if duplicate else r.get("id"),None if duplicate else r.get("version"))
        buttons(self,layout,save)


class RewardDetail(QDialog):
    def __init__(self,panel,seller,data=None):
        super().__init__(panel)
        self.panel,self.seller,self.snapshot = panel,seller,data
        self.setWindowTitle(f"Premios · {seller}")
        self.resize(1200,740)
        self.layout_box = QVBoxLayout(self)
        self.refresh()

    def refresh(self):
        saved = capture_tables(self)
        while self.layout_box.count():
            item = self.layout_box.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().deleteLater()
        data = self.snapshot if self.snapshot is not None else self.panel.engine.calculate(self.panel.key)
        self.current = next(s for s in data["sellers"] if s["seller"]==self.seller)
        table,filterable,_=widgets()
        self.layout_box.addWidget(QLabel(f"{self.seller} · {data['week_id']}\nComisión base 3%: {display(self.current['base_commission'],'money')}   "
            f"Premios: {display(self.current['total_awards'],'money')}   Total variable: {display(self.current['total_variable'],'money')}"))
        self.grid=table(["ID","Grupo","Nivel","Premio","Actual","Objetivo","Operador","Progreso %","Falta / explicación","Estado","Monto"],
            [[r["rule"]["id"],r["rule"]["group"],r["rule"]["level"] if r["rule"]["level"] is not None else "—",r["rule"]["name"],
              r["actual"] if r["actual"] is not None else "No disponible",r["target"],r["rule"]["operator"],r["progress"] if r["progress"] is not None else "—",
              r["explanation"],r["status"],r["amount"]] for r in self.current["results"]])
        self.layout_box.addWidget(filterable(self.grid))
        format_columns(self.grid,{7:"percent",10:"money"})
        for i in range(self.grid.rowCount()):
            result=next(r for r in self.current["results"] if r["rule"]["id"]==int(self.grid.item(i,0).text()))
            unit=METRICS[result["rule"]["metric"]][1]
            for col in (4,5):
                item=self.grid.item(i,col)
                if hasattr(item,"value"):item.setText(display(item.value,unit))
        self.progress = QProgressBar(); self.progress.setRange(0,100)
        self.layout_box.addWidget(self.progress)
        def selected():
            row=self.selected()
            value=row["progress"] if row else None
            self.progress.setValue(max(0,min(100,int(value or 0))))
            self.progress.setFormat(f"{display(value)}%" if value is not None else "Sin valor disponible")
        self.grid.itemSelectionChanged.connect(selected)
        self.grid.sortItems(2,Qt.AscendingOrder)
        self.grid.sortItems(1,Qt.AscendingOrder)
        if self.grid.rowCount():self.grid.selectRow(0)
        actions=QHBoxLayout()
        readonly=self.snapshot is not None or self.panel.engine.store.week(self.panel.key)["status"]=="CERRADA"
        for title,action in [("Ingresar valor manual",self.manual),("Invalidar premio",lambda:self.invalidate(False)),
                             ("Invalidar todos",lambda:self.invalidate(True)),("Revertir invalidación",self.revoke),
                             ("Control final del vendedor",self.control)]:
            button=QPushButton(title);button.setEnabled(not readonly);button.clicked.connect(lambda _,fn=action:self.run(fn));actions.addWidget(button)
        self.layout_box.addLayout(actions)
        self.layout_box.addWidget(QLabel("Los premios se suman. La barra se limita a 100%; el porcentaje conserva el progreso real.\n"
            "Control final registra valores y nota de Administración. Confirmado se aplica al cerrar la semana."))
        restore_tables(self,saved)

    def selected(self):
        row=self.grid.currentRow()
        return next((r for r in self.current["results"] if r["rule"]["id"]==int(self.grid.item(row,0).text())),None) if row>=0 else None

    def run(self,action):
        try:
            action()
        except (ValueError,OSError) as error:
            QMessageBox.warning(self,"Premios",str(error))
            return
        self.panel.refresh();self.refresh()

    def entry_dialog(self,title,with_value=False,initial=None):
        _,_,date_edit=widgets()
        d=QDialog(self);d.setWindowTitle(title);d.resize(540,440);layout=QVBoxLayout(d);form=QFormLayout()
        fields={}
        if with_value:
            fields["value"]=spin(initial,4);fields["value"].setMinimum(0);form.addRow("Valor verificado",fields["value"])
        fields["date"]=date_edit(self.panel.engine.service.now());form.addRow("Fecha",fields["date"])
        fields["reason"]=QLineEdit();form.addRow("Motivo",fields["reason"])
        fields["note"]=QTextEdit();form.addRow("Nota / clientes verificados",fields["note"])
        fields["observation"]=QLineEdit();form.addRow("Observación",fields["observation"])
        layout.addLayout(form)
        return d,layout,fields

    def manual(self):
        row=self.selected()
        if not row or not row["rule"]["manual"]:raise ValueError("Seleccioná un premio manual")
        d,layout,f=self.entry_dialog("Valor verificado",True,row["actual"])
        f["reason"].setEnabled(False)
        buttons(d,layout,lambda:self.panel.engine.manual(self.panel.key,self.seller,row["rule"]["id"],f["value"].value(),
            f["note"].toPlainText(),f["date"].date().toString("yyyy-MM-dd"),f["observation"].text()))
        d.exec()

    def invalidate(self,all_rules):
        row=self.selected()
        if not all_rules and not row:raise ValueError("Seleccioná el premio a invalidar")
        d,layout,f=self.entry_dialog("Invalidar TODOS los premios" if all_rules else "Invalidar premio seleccionado")
        buttons(d,layout,lambda:self.panel.engine.invalidate(self.panel.key,self.seller,None if all_rules else row["rule"]["id"],
            f["reason"].text(),f["date"].date().toString("yyyy-MM-dd"),f["note"].toPlainText()+"\n"+f["observation"].text()))
        d.exec()

    def revoke(self):
        from PySide6.QtWidgets import QInputDialog
        invalidations=self.panel.engine.store.query("SELECT * FROM reward_invalidations WHERE week_id=? AND seller=? AND revoked_at IS NULL",(self.panel.key,self.seller))
        if not invalidations:raise ValueError("No hay invalidaciones vigentes")
        labels=[f"#{i['id']} · {'Todos' if i['rule_id'] is None else 'Premio '+str(i['rule_id'])} · {i['reason']}" for i in invalidations]
        chosen,ok=QInputDialog.getItem(self,"Revertir invalidación","Elegí la invalidación",labels,0,False)
        if ok:
            reason,ok=QInputDialog.getText(self,"Motivo","Motivo de la reversión")
            if ok:self.panel.engine.revoke_invalidation(self.panel.key,invalidations[labels.index(chosen)]["id"],reason)

    def control(self):
        _,_,date_edit=widgets()
        d=QDialog(self);d.setWindowTitle("Control final · "+self.seller);d.resize(660,640)
        layout=QVBoxLayout(d);label=QLabel("Revisá los valores definitivos después de devoluciones/rechazos. Podés corregir cada métrica.\n"
            "No se interpretan adjuntos automáticamente. Cambiar fuentes, reglas o valores manuales obliga a reconfirmar.")
        label.setWordWrap(True);layout.addWidget(label)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);scroll.setWidget(body);layout.addWidget(scroll)
        values={"sale_net||":self.current["sale_net"]};labels={"sale_net||":"Venta final antes de IVA"}
        for row in self.current["results"]:
            if not row["rule"]["manual"]:
                key=metric_key(row["rule"]);values[key]=row["actual"];labels[key]=METRICS[row["rule"]["metric"]][0]+" "+row["rule"]["provider"]+" "+row["rule"]["article"]
        inputs={}
        for key,value in values.items():
            field=QLineEdit("" if value is None else str(value));field.setPlaceholderText("Dato faltante: completar para confirmar")
            form.addRow(labels[key],field);inputs[key]=field
        day=date_edit(self.panel.engine.service.now());form.addRow("Fecha de control",day)
        note=QTextEdit();note.setMaximumHeight(100);form.addRow("Nota obligatoria",note)
        confirmed=QCheckBox("Verifiqué estos valores finales y sus ajustes");form.addRow(confirmed)
        def save():
            if not confirmed.isChecked():raise ValueError("Marcá la confirmación del control final")
            def parse(text):
                text=text.strip().replace("$","").replace(" ","")
                if "," in text:text=text.replace(".","").replace(",",".")
                elif text.count(".")>1:text=text.replace(".","")
                return float(text)
            parsed={k:parse(w.text()) for k,w in inputs.items() if w.text().strip()}
            if any(not w.text().strip() for w in inputs.values()):raise ValueError("Completá los valores finales que faltan")
            self.panel.engine.confirm_control(self.panel.key,self.seller,parsed,note.toPlainText(),day.date().toString("yyyy-MM-dd"),self.current["source_signature"])
        buttons(d,layout,save);d.exec()


class RewardsPanel(QWidget):
    def __init__(self,service,key,metrics,parent=None):
        super().__init__(parent)
        self.engine=RewardService(service);self.key=key;self.metrics=metrics
        layout=QVBoxLayout(self)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.refresh(initial=True)

    def run(self,action):
        try:action()
        except (ValueError,OSError) as error:QMessageBox.warning(self,"Premios",str(error));return
        self.refresh()

    def refresh(self,initial=False):
        saved=capture_tables(self);index=self.tabs.currentIndex()
        if not initial:self.metrics=self.engine.service.metrics(self.key)
        self.data=self.engine.calculate(self.key,self.metrics)
        while self.tabs.count():
            page=self.tabs.widget(0);self.tabs.removeTab(0);page.deleteLater()
        self.tabs.addTab(self.week_tab(),"Semana seleccionada")
        self.tabs.addTab(self.config_tab(),"Configuración")
        self.tabs.addTab(self.history_tab(),"Historial")
        self.tabs.setCurrentIndex(max(0,index));restore_tables(self,saved)

    def config_tab(self):
        table,filterable,_=widgets();page=QWidget();layout=QVBoxLayout(page)
        label=QLabel("Reglas semanales acumulativas. Vigencia por lunes de la semana. Editar reglas nunca modifica los cierres guardados.")
        label.setWordWrap(True);layout.addWidget(label)
        self.rules=self.engine.rules()
        self.rules_table=table(["ID","Nombre","Grupo","Nivel","Métrica","Operador","Objetivo","Premio","Activa","Desde","Hasta","Vendedores"],
            [[r["id"],r["name"],r["group"],r["level"] if r["level"] is not None else "—",METRICS[r["metric"]][0],r["operator"],r["target"],r["amount"],
              "Sí" if r["active"] else "No",r["date_from"],r["date_to"] or "Sin límite",", ".join(r["scope"]) or "Todos"] for r in self.rules])
        layout.addWidget(filterable(self.rules_table));actions=QHBoxLayout()
        format_columns(self.rules_table,{7:"money"})
        for title,action in [("Crear premio",lambda:self.rule_dialog()),("Editar",lambda:self.rule_dialog(self.selected_rule())),
                             ("Duplicar",lambda:self.rule_dialog(self.selected_rule(),True)),("Activar / desactivar",self.toggle),
                             ("Archivar",self.archive)]:
            b=QPushButton(title);b.clicked.connect(lambda _,fn=action:self.run(fn));actions.addWidget(b)
        layout.addLayout(actions)
        return page

    def selected_rule(self):
        row=self.rules_table.currentRow()
        if row<0:raise ValueError("Seleccioná una regla")
        return next(r for r in self.rules if r["id"]==int(self.rules_table.item(row,0).text()))

    def rule_dialog(self,rule=None,duplicate=False):
        RuleDialog(self.engine,self.key,self.metrics,rule,duplicate,self).exec()

    def toggle(self):
        rule=dict(self.selected_rule());rule["active"]=not rule["active"]
        self.engine.save_rule(rule,rule["id"],rule["version"])

    def archive(self):
        rule=self.selected_rule()
        if QMessageBox.question(self,"Archivar premio",f"¿Archivar {rule['name']}? Los cierres históricos se conservan.")==QMessageBox.Yes:
            self.engine.archive(rule["id"])

    def week_tab(self):
        table,filterable,_=widgets();page=QWidget();layout=QVBoxLayout(page)
        if self.data.get("legacy"):
            layout.addWidget(QLabel(self.data["message"]));return page
        ratio=self.data["cost_pct"]
        self.alert=QLabel(("ALERTA: COSTO COMERCIAL MAYOR AL 7% · " if self.data["over_seven_percent"] else "Costo comercial · ")+display(ratio,"percent")+
                         "   |   Comisión 3% + premios / venta antes de IVA. No se recorta ningún premio.")
        self.alert.setWordWrap(True)
        if self.data["over_seven_percent"]:self.alert.setStyleSheet("background:#d91c28;color:white;padding:12px;font-weight:bold;")
        layout.addWidget(self.alert)
        label=QLabel("Comisión y premios son conceptos separados. Premios abiertos: estimados, no liquidables.\n"
            "Doble clic en un vendedor para ver escalones, cargar valores manuales, invalidar premios y confirmar el control final.")
        label.setWordWrap(True);layout.addWidget(label)
        self.seller_table=table(["Vendedor","Venta bruta","Devoluciones","Venta neta antes IVA","Cobertura %","Conversión %","Ticket antes IVA","Cumplidos","Pendientes","Premios","Comisión 3%","Total variable","Control final"],
            [[s["seller"],s.get("sale_gross") if s.get("sale_gross") is not None else "No disponible",s.get("returns",0),s["sale_net"] if s["sale_net"] is not None else "No disponible",s["coverage"],s["conversion"],
              s["ticket"] if s["ticket"] is not None else "—",s["reached"],s["pending"],s["total_awards"],
              s["base_commission"] if s["base_commission"] is not None else "—",s["total_variable"] if s["total_variable"] is not None else "—",
              "Verificado" if s["control_valid"] else "Pendiente"] for s in self.data["sellers"]])
        self.seller_table.cellDoubleClicked.connect(lambda row,_:RewardDetail(self,self.seller_table.item(row,0).text()).exec())
        format_columns(self.seller_table,{1:"money",2:"money",3:"money",4:"percent",5:"percent",6:"money",9:"money",10:"money",11:"money"})
        layout.addWidget(filterable(self.seller_table));actions=QHBoxLayout()
        b=QPushButton("Recalcular premios");b.setEnabled(self.engine.store.week(self.key)["status"]!="CERRADA")
        b.clicked.connect(lambda:self.run(lambda:self.engine.calculate(self.key,persist=True)));actions.addWidget(b)
        b=QPushButton("Exportar Excel · todos los vendedores");b.clicked.connect(lambda:self.run(lambda:self.export(self.data)));actions.addWidget(b)
        layout.addLayout(actions);return page

    def export(self,data):
        path,_=QFileDialog.getSaveFileName(self,"Liquidación de comisiones y premios",str(Path.home()/"Documents"/f"premios_{data['week_id']}.xlsx"),"Excel (*.xlsx)")
        if path:
            export_rewards(self.engine.service.export_path(path,".xlsx"),data)
            QMessageBox.information(self,"Exportación lista",path)

    def history_tab(self):
        table,filterable,_=widgets();page=QWidget();layout=QVBoxLayout(page)
        self.history=self.engine.store.query("SELECT * FROM snapshots WHERE kind='cierre' ORDER BY id DESC")
        self.history_table=table(["ID","Semana","Cerrada en","Revisión de fuentes"],[[r["id"],r["week_id"],r["created_at"],r["source_revision"]] for r in self.history])
        layout.addWidget(QLabel("Cada cierre conserva reglas, valores, notas e invalidaciones originales. Una reapertura no borra cierres anteriores."))
        layout.addWidget(filterable(self.history_table));actions=QHBoxLayout()
        for text,fn in [("Ver cierre",self.view_history),("Exportar cierre seleccionado",lambda:self.export(self.history_data()))]:
            b=QPushButton(text);b.clicked.connect(lambda _,action=fn:self.run(action));actions.addWidget(b)
        layout.addLayout(actions);return page

    def history_data(self):
        row=self.history_table.currentRow()
        if row<0:raise ValueError("Seleccioná un cierre")
        snapshot=next(r for r in self.history if r["id"]==int(self.history_table.item(row,0).text()))
        if file_hash(snapshot["file_path"])!=snapshot["hash"]:raise ValueError("El snapshot fue alterado fuera de la aplicación")
        awards=json.loads(Path(snapshot["file_path"]).read_text(encoding="utf-8")).get("awards")
        if not awards:raise ValueError("Ese cierre es anterior al sistema de premios")
        return awards

    def view_history(self):
        from PySide6.QtWidgets import QInputDialog
        data=self.history_data();names=[s["seller"] for s in data["sellers"]]
        if not names:raise ValueError("El cierre no tiene vendedores")
        seller,ok=QInputDialog.getItem(self,"Detalle histórico","Vendedor",names,0,False)
        if ok:RewardDetail(self,seller,data).exec()
