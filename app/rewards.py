"""Premios simples acumulativos sobre métricas existentes y el mismo SQLite semanal."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import operator

from app.review_data import normalize_seller, normalize_text
from app.week_store import timestamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS reward_meta(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
INSERT OR IGNORE INTO reward_meta VALUES(1,0);
CREATE TABLE IF NOT EXISTS reward_rules(
 id INTEGER PRIMARY KEY, payload TEXT NOT NULL, active INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reward_results(
 week_id TEXT NOT NULL REFERENCES weeks(id), seller TEXT NOT NULL, rule_id INTEGER NOT NULL REFERENCES reward_rules(id),
 payload TEXT NOT NULL, calculated_at TEXT NOT NULL, PRIMARY KEY(week_id,seller,rule_id));
CREATE TABLE IF NOT EXISTS reward_manual_values(
 week_id TEXT NOT NULL REFERENCES weeks(id), seller TEXT NOT NULL, rule_id INTEGER NOT NULL REFERENCES reward_rules(id),
 value TEXT NOT NULL, note TEXT NOT NULL, date TEXT NOT NULL, observation TEXT NOT NULL, timestamp TEXT NOT NULL,
 PRIMARY KEY(week_id,seller,rule_id));
CREATE TABLE IF NOT EXISTS reward_invalidations(
 id INTEGER PRIMARY KEY, week_id TEXT NOT NULL REFERENCES weeks(id), seller TEXT NOT NULL,
 rule_id INTEGER REFERENCES reward_rules(id), reason TEXT NOT NULL, date TEXT NOT NULL,
 note TEXT NOT NULL, timestamp TEXT NOT NULL, revoked_at TEXT, revoke_reason TEXT);
CREATE TABLE IF NOT EXISTS reward_controls(
 week_id TEXT NOT NULL REFERENCES weeks(id), seller TEXT NOT NULL, source_signature TEXT NOT NULL,
 values_json TEXT NOT NULL, note TEXT NOT NULL, date TEXT NOT NULL, timestamp TEXT NOT NULL,
 PRIMARY KEY(week_id,seller));
CREATE TABLE IF NOT EXISTS reward_audit(
 id INTEGER PRIMARY KEY, week_id TEXT, action TEXT NOT NULL, payload TEXT NOT NULL, timestamp TEXT NOT NULL);
INSERT OR IGNORE INTO schema_version VALUES(3);
"""

# Registro extensible: etiqueta, unidad, fuente y campo. Ninguna regla combina condiciones.
METRICS = {
    "sale_net": ("Venta semanal antes de IVA", "money", "orders", "sale_net"),
    "coverage": ("Cobertura", "percent", "sigo", "coverage_pct"),
    "conversion": ("Conversión", "percent", "sigo", "conversion_pct"),
    "ticket": ("Ticket promedio antes de IVA", "money", "orders", "average_ticket_net"),
    "buyers": ("Clientes compradores", "count", "orders", "buyers"),
    "orders": ("Pedidos lógicos", "count", "orders", "logical_orders"),
    "mix": ("Mix de artículos por cliente", "mix", "articles", "average_article_mix"),
    "provider_sale": ("Venta proveedor antes de IVA", "money", "provider", "sale_net"),
    "provider_buyers": ("Compradores del proveedor", "count", "provider", "clients"),
    "provider_coverage": ("Penetración del proveedor", "percent", "provider", "buyer_coverage_pct"),
    "article_sale": ("Venta artículo antes de IVA", "money", "article", "sale_net"),
    "article_quantity": ("Bultos del artículo", "quantity", "article", "quantity"),
    "article_buyers": ("Compradores del artículo", "count", "article", "clients"),
    "new_clients": ("Clientes nuevos (manual)", "count", "manual", ""),
    "reactivated_clients": ("Clientes reactivados (manual)", "count", "manual", ""),
}
OPERATORS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "=": operator.eq}


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Ingresá un número válido") from None
    if not result.is_finite():
        raise ValueError("El número debe ser finito")
    return result


def money_value(value):
    return float(number(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def metric_key(rule):
    return "|".join([rule["metric"], rule.get("provider", ""), rule.get("article", "")])


def display(value, unit="number"):
    if value is None:
        return "No disponible"
    text = (f"{value:,.0f}" if unit=="count" else f"{value:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")
    return ("$" if unit == "money" else "") + text + ("%" if unit == "percent" else "")


def compare(actual, rule):
    """Comparación decimal; el texto de progreso no se limita a 100%."""
    target, value = number(rule["target"]), number(actual)
    op = rule["operator"]
    reached = OPERATORS[op](value, target)
    unit = METRICS[rule["metric"]][1]
    progress = float(value / target * 100) if target else (100.0 if reached else 0.0)
    if op in ("<", "<="):
        progress = float(target / value * 100) if value > 0 else (100.0 if reached else 0.0)
    gap = abs(target - value) if not reached else Decimal(0)
    if reached:
        explanation = "Objetivo alcanzado"
    elif op == ">" and gap == 0:
        explanation = f"Debe superar {display(float(target), unit)}"
    elif op == "<" and gap == 0:
        explanation = f"Debe quedar por debajo de {display(float(target), unit)}"
    elif op == "=":
        explanation = f"Debe ser exactamente {display(float(target), unit)}"
    elif op in ("<", "<="):
        explanation = f"Debe reducir {display(float(gap), unit)}"
    else:
        suffix = {"percent": " puntos porcentuales", "count": " clientes compradores adicionales", "quantity": " bultos", "mix": " artículos por cliente"}.get(unit, "")
        if rule["metric"]=="orders":suffix=" pedidos lógicos adicionales"
        if rule["metric"]=="new_clients":suffix=" clientes nuevos adicionales"
        if rule["metric"]=="reactivated_clients":suffix=" clientes reactivados adicionales"
        explanation = "Faltan " + display(float(gap), unit if unit in {"money","count"} else "number") + suffix
    return reached, progress, float(gap), explanation


def metric_value(seller, rule):
    _, _, source, field = METRICS[rule["metric"]]
    available = seller.get("reward_availability", {})
    if source == "manual":
        return None
    if source in {"provider", "article", "articles"} and not available.get("orders", False):
        return None
    if not available.get("articles" if source in {"provider", "article"} else source, False):
        return None
    if rule["metric"] == "conversion" and not available.get("orders"):
        return None
    if source in {"provider", "article"}:
        entries = seller["providers" if source == "provider" else "articles"]
        found = [r for r in entries if (normalize_text(r["provider"]) == rule["provider"] if source == "provider"
                 else str(r["code"]) == rule["article"] and (not rule["provider"] or normalize_text(r["provider"]) == rule["provider"]))]
        if field == "clients":
            if source == "article":
                return len({c for r in found for c in r.get("client_codes", [])})
            return sum(r[field] for r in found)
        if field == "buyer_coverage_pct":
            return found[0][field] if found else 0
        return None if any(r.get(field) is None for r in found) else sum(r[field] for r in found)
    return seller.get(field)


def write_results(db, key, data):
    db.execute("DELETE FROM reward_results WHERE week_id=?",(key,))
    for seller in data["sellers"]:
        for row in seller["results"]:
            db.execute("INSERT INTO reward_results VALUES(?,?,?,?,?)",
                       (key,seller["seller"],row["rule"]["id"],json.dumps(row,ensure_ascii=False),data["calculated_at"]))


class RewardService:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def rules(self, archived=False):
        rows = self.store.query("SELECT * FROM reward_rules" + ("" if archived else " WHERE archived=0") + " ORDER BY id")
        return [dict(json.loads(r["payload"]), id=r["id"], version=r["version"], active=bool(r["active"]),
                     archived=bool(r["archived"]), created_at=r["created_at"], updated_at=r["updated_at"]) for r in rows]

    def audit(self, db, key, action, payload):
        db.execute("INSERT INTO reward_audit(week_id,action,payload,timestamp) VALUES(?,?,?,?)",
                   (key, action, json.dumps(payload, ensure_ascii=False, allow_nan=False), timestamp()))
        db.execute("UPDATE reward_meta SET revision=revision+1 WHERE id=1")

    def save_rule(self, data, rule_id=None, expected_version=None):
        defaults = dict(name="", description="", metric="sale_net", operator=">=", target=0, amount=0,
                        group="", level=None, provider="", article="", manual=False, active=True,
                        date_from=date.today().isoformat(), date_to="", scope=[], observation="", periodicity="weekly")
        rule = {key: data.get(key, value) for key, value in defaults.items()}
        rule["name"] = rule["name"].strip()
        if not rule["name"] or rule["metric"] not in METRICS or rule["operator"] not in OPERATORS:
            raise ValueError("Revisá nombre, métrica y operador")
        for field in ("target", "amount"):
            rule[field] = float(number(rule[field]))
            if rule[field] < 0:
                raise ValueError("Objetivo y premio deben ser positivos o cero")
        if METRICS[rule["metric"]][1] == "count" and not number(rule["target"]) == int(rule["target"]):
            raise ValueError("El objetivo de clientes/pedidos debe ser entero")
        rule["amount"] = money_value(rule["amount"])
        date.fromisoformat(rule["date_from"])
        if rule["date_to"] and date.fromisoformat(rule["date_to"]) < date.fromisoformat(rule["date_from"]):
            raise ValueError("La fecha hasta debe ser posterior a desde")
        rule["provider"] = normalize_text(rule["provider"])
        rule["article"] = str(rule["article"]).strip()
        source = METRICS[rule["metric"]][2]
        if source == "provider" and not rule["provider"] or source == "article" and not rule["article"]:
            raise ValueError("Elegí el proveedor o código de artículo de la regla")
        if source != "article":
            rule["article"] = ""
        if source not in {"article", "provider"}:
            rule["provider"] = ""
        rule["manual"] = bool(rule["manual"] or source == "manual")
        rule["scope"] = sorted({normalize_seller(s) for s in rule["scope"] if s.strip()})
        rule["periodicity"] = "weekly"
        rule["level"] = int(rule["level"]) if rule["level"] is not None else None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            before = None
            if rule_id is not None:
                before = db.execute("SELECT * FROM reward_rules WHERE id=?", (rule_id,)).fetchone()
                if before is None or before["archived"]:
                    raise ValueError("Premio inexistente o archivado")
                if expected_version is not None and before["version"] != expected_version:
                    raise ValueError("La regla cambió; actualizá la configuración")
                db.execute("UPDATE reward_rules SET payload=?,active=?,version=version+1,updated_at=? WHERE id=?",
                           (json.dumps(rule, ensure_ascii=False), int(rule["active"]), timestamp(), rule_id))
            else:
                rule_id = db.execute("INSERT INTO reward_rules(payload,active,created_at,updated_at) VALUES(?,?,?,?)",
                    (json.dumps(rule, ensure_ascii=False), int(rule["active"]), timestamp(), timestamp())).lastrowid
            self.audit(db, None, "guardar_regla", {"id": rule_id, "before": dict(before) if before else None, "after": rule})
        return rule_id

    def archive(self, rule_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE reward_rules SET archived=1,active=0,version=version+1,updated_at=? WHERE id=?", (timestamp(), rule_id))
            self.audit(db, None, "archivar_regla", {"id": rule_id})

    def _validate_seller(self, key, seller):
        if seller not in {s["seller"] for s in self.service.metrics(key)["sellers"]}:
            raise ValueError("Vendedor inexistente o excluido de esta semana")

    def manual(self, key, seller, rule_id, value, note, day, observation=""):
        self._validate_seller(key, seller)
        rule = next((r for r in self.rules() if r["id"] == rule_id), None)
        if not rule or not rule["manual"]:
            raise ValueError("La regla no es manual")
        val = number(value)
        if val < 0 or METRICS[rule["metric"]][1] == "count" and val != int(val):
            raise ValueError("Ingresá un valor no negativo; clientes y pedidos deben ser enteros")
        date.fromisoformat(day)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.assert_open(db, key)
            before = db.execute("SELECT * FROM reward_manual_values WHERE week_id=? AND seller=? AND rule_id=?", (key,seller,rule_id)).fetchone()
            db.execute("INSERT OR REPLACE INTO reward_manual_values VALUES(?,?,?,?,?,?,?,?)",
                       (key,seller,rule_id,str(val),note,day,observation,timestamp()))
            self.audit(db,key,"valor_manual", {"seller":seller,"rule_id":rule_id,"value":str(val),"note":note,
                       "date":day,"observation":observation,"before":dict(before) if before else None})

    def invalidate(self, key, seller, rule_id, reason, day, note=""):
        self._validate_seller(key, seller)
        if not reason.strip():
            raise ValueError("El motivo es obligatorio")
        date.fromisoformat(day)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.assert_open(db,key)
            db.execute("INSERT INTO reward_invalidations(week_id,seller,rule_id,reason,date,note,timestamp) VALUES(?,?,?,?,?,?,?)",
                       (key,seller,rule_id,reason,day,note,timestamp()))
            self.audit(db,key,"invalidar_premios",dict(seller=seller,rule_id=rule_id,reason=reason,date=day,note=note))

    def revoke_invalidation(self, key, invalidation_id, reason):
        if not reason.strip():
            raise ValueError("Indicá por qué se revierte la invalidación")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.assert_open(db,key)
            db.execute("UPDATE reward_invalidations SET revoked_at=?,revoke_reason=? WHERE id=? AND week_id=? AND revoked_at IS NULL",
                       (timestamp(),reason,invalidation_id,key))
            self.audit(db,key,"revertir_invalidacion",dict(id=invalidation_id,reason=reason))

    def applicable(self, key):
        week = self.store.week(key)
        # Una regla semanal rige por el lunes de la semana, sin prorrateos.
        return sorted([r for r in self.rules() if r["active"] and r["date_from"] <= week["start_date"]
                       and (not r["date_to"] or r["date_to"] >= week["start_date"])],
                      key=lambda r:(r["group"],r["level"] if r["level"] is not None else 0,r["id"]))

    def source(self, key, seller, rules, manual, revision):
        payload = {"seller":seller,"rules":rules,"manual":manual,"source_revision":revision}
        return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def calculate(self, key, data=None, final=False, persist=False):
        data = data if data is not None else self.service.metrics(key)
        if self.store.week(key)["status"] == "CERRADA":
            return deepcopy(data.get("awards") or {"rules":[],"sellers":[],"legacy":True,"message":"Cierre anterior al sistema de premios; no se recalcula."})
        revision = self.store.query("SELECT revision FROM reward_meta WHERE id=1")[0]["revision"]
        rules = self.applicable(key)
        manuals = self.store.query("SELECT * FROM reward_manual_values WHERE week_id=?",(key,))
        invalidations = self.store.query("SELECT * FROM reward_invalidations WHERE week_id=?",(key,))
        controls = {r["seller"]:r for r in self.store.query("SELECT * FROM reward_controls WHERE week_id=?",(key,))}
        results = []
        for seller in data["sellers"]:
            name = seller["seller"]
            selected = [r for r in rules if not r["scope"] or name in r["scope"]]
            manual_rows = [r for r in manuals if r["seller"]==name]
            manual = {r["rule_id"]:r for r in manual_rows}
            signature = self.source(key,seller,selected,manual_rows,data["source_revision"])
            control = controls.get(name)
            controlled = bool(control and control["source_signature"] == signature)
            overrides = json.loads(control["values_json"]) if controlled else {}
            base = overrides.get("sale_net||", seller.get("sale_net") if seller.get("reward_availability",{}).get("orders") else None)
            commission = money_value(number(base)*Decimal("0.03")) if base is not None else None
            rows = []
            for rule in selected:
                manual_row = manual.get(rule["id"])
                actual = (float(manual_row["value"]) if manual_row else None) if rule["manual"] else metric_value(seller,rule)
                if not rule["manual"]:
                    actual = overrides.get(metric_key(rule),actual)
                invalid = [i for i in invalidations if i["seller"]==name and not i["revoked_at"] and i["rule_id"] in (None,rule["id"])]
                reached, progress, gap, explanation = compare(actual,rule) if actual is not None else (False,None,None,"Métrica no disponible; faltan datos o control manual")
                if invalid:
                    status = "INVALIDADO"
                    explanation = "Invalidado: " + "; ".join(i["reason"] for i in invalid)
                elif actual is None:
                    status = "PENDIENTE_CONTROL_MANUAL" if rule["manual"] else "PENDIENTE"
                elif reached:
                    status = "CONFIRMADO" if final and controlled else "CUMPLIDO_PRELIMINAR"
                else:
                    status = "NO_ALCANZADO" if final and controlled else "PENDIENTE"
                rows.append(dict(rule=deepcopy(rule), actual=actual, target=rule["target"], progress=progress,
                    gap=gap, explanation=explanation, status=status, amount=rule["amount"],
                    earned=rule["amount"] if status in {"CUMPLIDO_PRELIMINAR","CONFIRMADO"} else 0,
                    manual=manual_row, invalidations=invalid))
            estimated = money_value(sum(number(r["earned"]) for r in rows))
            results.append(dict(seller=name,sale_net=base,coverage=overrides.get("coverage||",seller.get("coverage_pct")),conversion=overrides.get("conversion||",seller.get("conversion_pct")),
                ticket=overrides.get("ticket||",seller.get("average_ticket_net")),base_commission=commission,
                total_awards=estimated,total_variable=money_value(number(commission)+number(estimated)) if commission is not None else None,
                reached=sum(r["status"] in {"CUMPLIDO_PRELIMINAR","CONFIRMADO"} for r in rows),
                pending=sum(r["status"] in {"PENDIENTE","PENDIENTE_CONTROL_MANUAL"} for r in rows),
                results=rows,source_signature=signature,control_valid=controlled,control=control))
        complete = all(r["base_commission"] is not None for r in results)
        total_sale = money_value(sum(number(r["sale_net"]) for r in results)) if complete else None
        total_commission = money_value(sum(number(r["base_commission"]) for r in results)) if complete else None
        total_awards = money_value(sum(number(r["total_awards"]) for r in results))
        ratio = float((number(total_commission)+number(total_awards))/number(total_sale)*100) if total_sale and total_sale>0 else None
        result = dict(week_id=key,week_status="CERRADA" if final else data["status"],revision=revision,source_revision=data["source_revision"],
            calculated_at=timestamp(),rules=rules,sellers=results,manual_values=manuals,invalidations=invalidations,
            sale_net=total_sale,base_commission=total_commission,total_awards=total_awards,cost_pct=ratio,
            over_seven_percent=ratio is not None and ratio>7,confirmed=final and all(r["control_valid"] for r in results))
        if persist:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.store.assert_open(db,key,data["source_revision"])
                if revision != db.execute("SELECT revision FROM reward_meta WHERE id=1").fetchone()[0]:
                    raise ValueError("Los premios cambiaron durante el cálculo; recalculá")
                write_results(db,key,result)
                db.execute("INSERT INTO reward_audit(week_id,action,payload,timestamp) VALUES(?,?,?,?)",
                           (key,"recalcular",json.dumps({"source_revision":data["source_revision"],"reward_revision":revision}),timestamp()))
        return result

    def confirm_control(self,key,seller,values,note,day,signature):
        if not note.strip():
            raise ValueError("Registrá una nota del control final")
        date.fromisoformat(day)
        current = self.calculate(key)
        row = next((s for s in current["sellers"] if s["seller"]==seller),None)
        if row is None or row["source_signature"]!=signature:
            raise ValueError("Los datos cambiaron; abrí nuevamente el control")
        allowed = {"sale_net||"} | {metric_key(r["rule"]) for r in row["results"] if not r["rule"]["manual"]}
        if set(values)-allowed:
            raise ValueError("Control con métricas desconocidas")
        normalized = {k:float(number(v)) for k,v in values.items()}
        if "sale_net||" not in normalized:
            raise ValueError("Falta la venta final antes de IVA")
        for r in row["results"]:
            rule = r["rule"]
            if not rule["manual"] and metric_key(rule) in normalized and METRICS[rule["metric"]][1]=="count":
                value = normalized[metric_key(rule)]
                if value<0 or value!=int(value):
                    raise ValueError("Los conteos deben ser enteros no negativos")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.assert_open(db,key,current["source_revision"])
            if current["revision"]!=db.execute("SELECT revision FROM reward_meta WHERE id=1").fetchone()[0]:
                raise ValueError("Los premios cambiaron; abrí nuevamente el control")
            before = db.execute("SELECT * FROM reward_controls WHERE week_id=? AND seller=?",(key,seller)).fetchone()
            db.execute("INSERT OR REPLACE INTO reward_controls VALUES(?,?,?,?,?,?,?)",
                       (key,seller,signature,json.dumps(normalized),note,day,timestamp()))
            self.audit(db,key,"control_final",dict(seller=seller,values=normalized,note=note,date=day,before=dict(before) if before else None))

    def closing(self,key,data):
        result = self.calculate(key,data,final=True)
        if result["rules"]:
            missing = [s["seller"] for s in result["sellers"] if not s["control_valid"] or s["base_commission"] is None
                       or any(r["status"] in {"PENDIENTE","PENDIENTE_CONTROL_MANUAL"} for r in s["results"])]
            if missing:
                raise ValueError("Premios: falta control final o valores disponibles para " + ", ".join(missing))
        return result
