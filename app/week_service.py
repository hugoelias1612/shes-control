"""Casos de uso semanales: progreso, revisión, métricas y cierre administrativo."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

import pandas as pd

from app.importers import parse_date_series
from app.processor import aggregate_articles, aggregate_providers, percentage, client_code
from app.review_data import (ReviewSession, build_logical_orders, build_article_map,
    load_points_file, load_orders_file, load_porcliente_file, normalize_seller,
    clean_text, is_yes, review_snapshot, parse_client, format_date)
from app.week_calendar import BRANCHES, DAY_NAMES, as_date, week_days
from app.week_store import WeekStore, file_hash, timestamp
from app.storage import write_json


class WeekService:
    def __init__(self, store=None, today=None):
        self.store = store or WeekStore()
        self.today = today  # Inyectable en tests; en producción se consulta al refrescar.
        self._cache = {}

    def now(self):
        return self.today or date.today()

    def progress(self, key):
        week = self.store.week(key)
        uploads = self.store.uploads(key, active=True)
        indexed = {u["logical_key"]: u for u in uploads}
        work = {(w["date"], w["branch"]): w for w in self.store.workdays(key)}
        liquidations = {x["date"]: x for x in self.store.liquidations(key)}
        days = []
        for day in week_days(week["start_date"]):
            iso = day.isoformat()
            sunday = day.weekday() == 6
            branches = {}
            missing = []
            for branch in BRANCHES:
                row = work[(iso, branch)]
                if sunday:
                    state = "NO APLICA (domingo)"
                elif not row["worked"]:
                    state = "NO SE TRABAJÓ"
                elif f"puntos:{iso}:{branch}" in indexed:
                    state = "CARGADO"
                elif day >= self.now():
                    state = "TODAVÍA NO CORRESPONDE"
                else:
                    state = "PENDIENTE"
                branches[branch] = state
                if state == "PENDIENTE":
                    missing.append(f"Puntos {branch}")
            not_worked = not sunday and all(not work[(iso, b)]["worked"] for b in BRANCHES)
            reports = {kind: bool(kind in indexed and indexed[kind]["coverage_start"] <= iso <= indexed[kind]["coverage_end"])
                       for kind in ("pedidos", "porcliente")}
            if not not_worked:
                missing.extend(kind for kind, present in reports.items() if not present and day < self.now())
            points_ready = sunday or all(branches[b] in {"CARGADO", "NO SE TRABAJÓ"} for b in BRANCHES)
            commercial = not_worked or (points_ready and all(reports.values()))
            liq = liquidations[iso]
            if not_worked:
                state = "NO_TRABAJADA"
            elif day > self.now():
                state = "FUTURA"
            elif day == self.now():
                state = "EN_CURSO"
            elif not commercial:
                state = "PREVENTA_PENDIENTE"
            elif liq["confirmed_complete"]:
                state = "LIQUIDADA"
            else:
                state = "PREVENTA_COMPLETA"
            days.append({"date": iso, "name": DAY_NAMES[day.weekday()], "sunday": sunday,
                         "branches": branches, "reports": reports, "commercial_complete": commercial,
                         "state": state, "missing": missing, "no_work": not_worked,
                         "liquidations": liq, "reasons": {b: work[(iso, b)]["reason"] for b in BRANCHES}})
        commercial_complete = all(d["commercial_complete"] for d in days) and self.now().isoformat() > week["end_date"]
        required = [d for d in days if not d["no_work"]]
        liquidated = all(d["liquidations"]["confirmed_complete"] for d in required)
        status = week["status"]
        if status not in {"CERRADA", "REABIERTA"}:
            status = "LIQUIDACIONES_PENDIENTES" if commercial_complete and not liquidated else (
                "PREVENTA_COMPLETA" if commercial_complete else "EN_CURSO")
        return {"week": week, "days": days, "status": status, "commercial_complete": commercial_complete,
                "liquidations_complete": liquidated}

    def missing_explanation(self, key):
        progress = self.progress(key)
        lines = [f"Semana {progress['week']['start_date']} a {progress['week']['end_date']}"]
        for day in progress["days"]:
            lines.append(f"\n{day['name']} {day['date']}: {day['state'].replace('_', ' ')}")
            if day["sunday"]:
                lines.append("Domingo no requiere SIGO. Sus pedidos pertenecen a esta semana.")
            if day["missing"]:
                lines.append("Falta cargar: " + ", ".join(day["missing"]))
            if day["state"] in {"FUTURA", "EN_CURSO"}:
                lines.append("La jornada aún no terminó; sus archivos no se consideran faltantes.")
            for branch, reason in day["reasons"].items():
                if day["branches"][branch] == "NO SE TRABAJÓ":
                    lines.append(f"{branch}: no se trabajó" + (f" ({reason})" if reason else ""))
            liq = day["liquidations"]
            lines.append(f"Liquidaciones cargadas: {liq['count_uploaded']}. Completas: " +
                         ("confirmado" if liq["confirmed_complete"] else "sin confirmar"))
        lines.append("\nCierre comercial: " + ("completo" if progress["commercial_complete"] else
                     "pendiente de datos y/o jornadas aún no finalizadas"))
        lines.append("Cierre administrativo: " + ("liquidaciones confirmadas" if progress["liquidations_complete"] else
                     "falta confirmar las liquidaciones de las jornadas aplicables"))
        return "\n".join(lines)

    def build_session(self, key):
        week = self.store.week(key)
        cache_key = (key, week["revision"], self.now())
        uploads = self.store.uploads(key, active=True)
        for upload in uploads:
            if file_hash(upload["file_path"]) != upload["hash"]:
                raise ValueError(f"Archivo activo modificado fuera de SHES-Control: {upload['original_filename']}")
        if cache_key in self._cache:
            return deepcopy(self._cache[cache_key])
        work = {(w["date"], w["branch"]): bool(w["worked"]) for w in self.store.workdays(key)}
        activity = defaultdict(lambda: {"assigned": set(), "visited": set(), "days": set(), "sale_signal": set()})
        sellers = {normalize_seller(s) for u in uploads for s in json.loads(u["metadata"]).get("sellers", [])}
        warnings = []
        physical_upload = next((u for u in uploads if u["type"] == "pedidos"), None)
        for upload in uploads:
            if upload["type"] != "puntos":
                continue
            day, branch = upload["coverage_start"], upload["branch"]
            if not work[(day, branch)] or as_date(day) > self.now():
                continue
            if physical_upload and not physical_upload["coverage_start"] <= day <= physical_upload["coverage_end"]:
                continue  # No mezclar visitas de días que el reporte comercial aún no cubre.
            df = load_points_file(upload["file_path"])
            for _, row in df.iterrows():
                seller = normalize_seller(row.get("d_perso"))
                code = client_code(row.get("CodClienteEmpresa"))
                if not seller or not code:
                    continue
                sellers.add(seller)
                activity[seller]["assigned"].add((day, code))
                activity[seller]["days"].add(day)
                if is_yes(row.get("visitado")):
                    activity[seller]["visited"].add((day, code))
                if clean_text(row.get("horaVenta")):
                    activity[seller]["sale_signal"].add((day, code))
        orders = []
        excluded_orders = []
        if physical_upload:
            df = load_orders_file(physical_upload["file_path"])
            df = df[df["NÚMERO PEDIDO"].notna()].copy()
            dates = parse_date_series(df["FECHA/HORA DE ALTA"])
            for day in week_days(week["start_date"]):
                if physical_upload["coverage_start"] <= day.isoformat() <= physical_upload["coverage_end"] and day <= self.now():
                    orders.extend(build_logical_orders(df, {}, day))
            selected = dates.notna() & dates.map(lambda d: False if pd.isna(d) else
                physical_upload["coverage_start"] <= d.isoformat() <= physical_upload["coverage_end"] and d <= self.now())
            excluded_orders = [{"number": clean_text(r["NÚMERO PEDIDO"]), "reason": "Fuera de rango comercial o fecha inválida",
                                "client_code": parse_client(r["CLIENTE"])[0],
                                "original_seller": normalize_seller(r["VENDEDOR DEL PEDIDO"]),
                                "delivery_date": format_date(r.get("FECHA ENTREGA"))}
                               for _, r in df[~selected].iterrows()]
            if excluded_orders:
                warnings.append(f"{len(excluded_orders)} pedidos fuera del rango seleccionado o sin fecha válida; no suman.")
            sellers.update(o.original_seller for o in orders)
        for seller, act in activity.items():
            registered = {(o.preventa_day, o.client_code) for o in orders if o.original_seller == seller}
            unmatched = act["sale_signal"] - registered
            if unmatched:
                warnings.append(f"{seller}: {len(unmatched)} registros de Hora Venta sin pedido conciliado; actividad SIGO conservada.")
        prior = self.store.latest_review(key)
        excluded = {s for s in sellers if s == "HUGO" or s.startswith("HUGO ")}
        if prior:
            payload = json.loads(prior["payload"])
            excluded = set(payload["excluded_sellers"]) | {s for s in excluded if s not in payload["sellers"]}
            assignments = {o["logical_id"]: o["assigned_seller"] for o in payload["orders"]}
            for order in orders:
                order.assigned_seller = assignments.get(order.logical_id, order.original_seller)
                sellers.add(order.assigned_seller)
            if prior["source_revision"] != week["revision"]:
                warnings.append("Hay cambios desde la revisión confirmada. Revisá y confirmá nuevamente antes del cierre.")
        else:
            warnings.append("Asignaciones preliminares: revisión semanal aún no confirmada.")
        session = ReviewSession(self.store.folder(key), sorted(sellers), orders, excluded,
                                f"{week['start_date']} – {week['end_date']}", warnings, excluded_orders)
        # Adjunta únicamente las líneas atribuibles a una jornada. El resto se calcula una vez a nivel semanal.
        article_orders, article_warnings = self.article_orders(key, session)
        session.warnings.extend(article_warnings)
        exact_articles = {o.logical_id: o.articles for o in article_orders if not o.logical_id.startswith("weekly:")}
        for order in session.orders:
            order.articles = exact_articles.get(order.logical_id, [])
        bundle = (session, dict(activity), article_orders, week["revision"])
        self._cache = {cache_key: deepcopy(bundle)}
        return bundle

    def article_orders(self, key, session):
        upload = next((u for u in self.store.uploads(key, active=True) if u["type"] == "porcliente"), None)
        if not upload:
            return [], ["PorCliente pendiente: venta disponible, artículos/proveedores todavía incompletos."]
        frame = load_porcliente_file(upload["file_path"])
        frame = frame[frame["Cod. Cliente"].notna() & frame["Código"].notna()].copy()
        mode = json.loads(upload["metadata"]).get("date_mode", "aggregate")
        warnings = []
        groups = [(None, frame)]
        if mode != "aggregate":
            dates = parse_date_series(frame["Descripción Período"])
            if dates.isna().any():
                warnings.append(f"{int(dates.isna().sum())} líneas PorCliente con fecha inválida no atribuidas.")
            groups = [(day, frame.loc[dates.eq(day)]) for day in sorted(set(dates.dropna()))]
        carriers = []
        eligible = [o for o in session.orders if not o.fully_annulled and
                    upload["coverage_start"] <= o.preventa_day <= upload["coverage_end"]]
        for period, rows in groups:
            for (client, seller), articles in build_article_map(rows).items():
                matching = [o for o in eligible if o.client_code == client and o.original_seller == seller]
                if mode == "commercial":
                    matching = [o for o in matching if o.preventa_day == period.isoformat()]
                elif mode == "delivery":
                    matching = [o for o in matching if period.strftime("%d/%m/%Y") in o.delivery_date.split(", ")]
                    collision = any(o.get("client_code") == client and o.get("original_seller") == seller
                                    and o.get("delivery_date") == period.strftime("%d/%m/%Y")
                                    for o in session.excluded_orders)
                    if matching and collision:
                        warnings.append(f"Artículos no atribuidos: cliente {client}, entrega {period}, compartida con pedidos fuera del rango comercial.")
                        continue
                if not matching:
                    warnings.append(f"Artículos sin pedido válido asociado: cliente {client}, vendedor {seller}, período {period or 'acumulado'}.")
                    continue
                destinations = {o.assigned_seller for o in matching}
                if len(destinations) != 1:
                    warnings.append(f"Artículos pendientes de atribución: cliente {client} con varias jornadas y distintos vendedores finales.")
                    continue
                carrier = deepcopy(matching[0])
                carrier.articles = articles
                if len(matching) > 1:
                    carrier.logical_id = f"weekly:{client}:{seller}:{period}"
                    carrier.valid_total = sum(o.valid_total for o in matching)
                    warnings.append(f"Cliente {client}: artículos contabilizados una sola vez en la semana; sin reparto inventado entre jornadas.")
                carriers.append(carrier)
        # Varios períodos de entrega pueden corresponder al mismo pedido lógico.
        merged = {}
        for carrier in carriers:
            if carrier.logical_id in merged:
                merged[carrier.logical_id].articles.extend(carrier.articles)
            else:
                merged[carrier.logical_id] = carrier
        for carrier in merged.values():
            difference = round(sum(a.total for a in carrier.articles) - carrier.valid_total, 2)
            if abs(difference) > 0.02:
                warnings.append(f"Diferencia PorCliente/pedidos: {carrier.client_code}, {carrier.original_seller}: {difference:+.2f}. Revisar importes.")
        return list(merged.values()), warnings

    def confirm_review(self, key, session, revision):
        if any(o.assigned_seller not in session.sellers or o.assigned_seller == "SIN ASIGNAR"
               for o in session.orders if not o.fully_annulled):
            raise ValueError("Asigná todos los pedidos válidos antes de confirmar")
        payload = review_snapshot(session)
        payload["confirmed_at"] = timestamp()
        path = self.store.save_review(key, payload, revision)
        self._cache.clear()
        return path

    def metrics(self, key):
        week = self.store.week(key)
        if week["status"] == "CERRADA":
            closed = next(s for s in self.store.snapshots(key) if s["kind"] == "cierre")
            if file_hash(closed["file_path"]) != closed["hash"]:
                raise ValueError("El snapshot de cierre fue alterado")
            return json.loads(Path(closed["file_path"]).read_text(encoding="utf-8"))
        session, activity, carriers, revision = self.build_session(key)
        progress = self.progress(key)
        included = [s for s in session.sellers if s not in session.excluded_sellers and s != "SIN ASIGNAR"]
        orders = [o for o in session.orders if not o.fully_annulled and o.assigned_seller in included]
        article_orders = [o for o in carriers if o.assigned_seller in included]
        total = sum(o.valid_total for o in orders)
        completed_days = {d["date"] for d in progress["days"] if d["commercial_complete"]
                          and not d["no_work"] and not d["sunday"] and as_date(d["date"]) < self.now()}

        def summarize(selected, article_selected, selected_sellers):
            sale = sum(o.valid_total for o in selected)
            buyers = {o.client_code for o in selected}
            assigned, visited, working_dates = set(), set(), set()
            operational_buyers = set()
            for seller in selected_sellers:
                act = activity.get(seller, {"assigned": set(), "visited": set(), "days": set()})
                assigned.update(act["assigned"])
                visited.update(act["visited"])
                working_dates.update(act["days"] & completed_days)
                operational_buyers.update((o.preventa_day, o.client_code) for o in selected
                    if o.assigned_seller == seller and o.preventa_day in act["days"])
            articles = aggregate_articles(article_selected, len(buyers), sale)
            providers = aggregate_providers(articles, sale, len(buyers))
            mix_pairs = {(o.client_code, a.code) for o in article_selected for a in o.articles}
            operational_sale = sum(o.valid_total for o in selected if o.preventa_day in working_dates)
            return {"sale": round(sale, 2), "buyers": len(buyers), "assigned_clients": len(assigned),
                    "visited_clients": len(visited), "not_visited_clients": len(assigned - visited),
                    "coverage_pct": round(percentage(len(visited), len(assigned)), 2),
                    "portfolio_use_pct": round(percentage(len(operational_buyers), len(assigned)), 2),
                    "conversion_pct": round(percentage(len(operational_buyers), len(visited)), 2),
                    "average_ticket": round(sale / len(buyers), 2) if buyers else 0,
                    "logical_orders": len({(o.client_code, o.assigned_seller, o.preventa_day) for o in selected}),
                    "average_article_mix": round(len(mix_pairs) / len(buyers), 2) if buyers else 0,
                    "working_days": len(working_dates),
                    "average_daily_sale": round(operational_sale / len(working_dates), 2) if working_dates else 0,
                    "articles": articles, "providers": providers}

        sellers = []
        for seller in included:
            values = summarize([o for o in orders if o.assigned_seller == seller],
                               [o for o in article_orders if o.assigned_seller == seller], [seller])
            values.update(seller=seller, company_share_pct=round(percentage(values["sale"], total), 2))
            sellers.append(values)
        company = summarize(orders, article_orders, included)
        articles, providers = company.pop("articles"), company.pop("providers")
        company.update(included_sellers=len(included), excluded_sellers=len(session.excluded_sellers),
                       original_sale=round(sum(o.original_total for o in session.orders if o.assigned_seller in included), 2))
        active = self.store.uploads(key, active=True)
        pedidos = next((u for u in active if u["type"] == "pedidos"), None)
        porcliente = next((u for u in active if u["type"] == "porcliente"), None)
        data_until = min(pedidos["coverage_end"], self.now().isoformat()) if pedidos and pedidos["coverage_start"] <= self.now().isoformat() else None
        articles_until = min(porcliente["coverage_end"], self.now().isoformat()) if porcliente and porcliente["coverage_start"] <= self.now().isoformat() else None
        complete_until = None
        for d in progress["days"]:
            if not d["commercial_complete"] or as_date(d["date"]) >= self.now():
                break
            complete_until = d["date"]
        sunday_orders = [o for o in orders if as_date(o.preventa_day).weekday() == 6]
        result = {"schema_version": 2, "week_id": key, "preventa_date": session.preventa_date,
                  "status": progress["status"], "final_numbers": False, "liquidations_required": True,
                  "processed_at": timestamp(), "source_revision": revision,
                  "data_until": data_until, "commercial_complete": progress["commercial_complete"],
                  "articles_until": articles_until, "complete_until": complete_until,
                  "company": company, "sellers": sorted(sellers, key=lambda s: s["sale"], reverse=True),
                  "articles": articles, "providers": providers, "warnings": session.warnings,
                  "review": review_snapshot(session), "active_upload_ids": [u["id"] for u in active],
                  "article_attributions": [asdict(o) for o in carriers],
                  "activity": {s: {name: sorted(entries) for name, entries in metrics.items()} for s, metrics in activity.items()},
                  "sunday": {"sale": round(sum(o.valid_total for o in sunday_orders), 2),
                             "logical_orders": len({(o.client_code, o.assigned_seller) for o in sunday_orders})},
                  "metric_basis": "Cobertura y conversión: pares cliente/jornada con SIGO activo. Domingo excluido. Promedio operativo: jornadas comerciales completas con actividad, sin domingo."}
        return result

    def process(self, key):
        data = self.metrics(key)
        if self.store.week(key)["status"] != "CERRADA":
            self.store.save_snapshot(key, data)
        return data

    def export(self, key, path):
        target = Path(path).resolve()
        repo = Path(__file__).resolve().parents[1]
        history = (self.store.root / "HISTORIAL").resolve()
        if repo == target or repo in target.parents or history == target or history in target.parents:
            raise ValueError("Exportá fuera del repositorio y del historial protegido")
        if target.suffix.lower() != ".json":
            raise ValueError("La exportación debe tener extensión .json")
        return write_json(target, self.metrics(key))

    def close(self, key):
        progress = self.progress(key)
        if not progress["commercial_complete"]:
            raise ValueError("Faltan datos comerciales o la semana todavía no terminó")
        if not progress["liquidations_complete"]:
            raise ValueError("Falta confirmar las liquidaciones de las jornadas aplicables")
        review = self.store.latest_review(key)
        if review is None or review["source_revision"] != self.store.week(key)["revision"]:
            raise ValueError("Confirmá la revisión de las versiones activas antes del cierre")
        data = self.metrics(key)
        data.update(status="CERRADA", closed_at=timestamp(), administrative_closed=True,
                    liquidations=self.store.liquidations(key), awards=None)
        return self.store.save_snapshot(key, data, kind="cierre", close=True)
