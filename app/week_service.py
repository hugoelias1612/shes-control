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
from app.review_data import (ReviewSession, build_logical_orders,
    load_points_file, load_orders_file, load_porcliente_file, normalize_seller,
    clean_text, is_yes, review_snapshot, parse_client, format_date)
from app.week_calendar import BRANCHES, DAY_NAMES, as_date, week_days, delivery_for_presale, presale_for_delivery
from app.week_store import WeekStore, file_hash, timestamp
from app.storage import write_json


class WeekService:
    def __init__(self, store=None, today=None):
        self.store = store or WeekStore()
        self.today = today  # Inyectable en tests; en producción se consulta al refrescar.
        self._cache = {}
        self._return_cache = {}

    def now(self):
        return self.today or date.today()

    def progress(self, key):
        week = self.store.week(key)
        uploads = self.store.uploads(key, active=True)
        indexed = {u["logical_key"]: u for u in uploads}
        point_days = set()
        for u in uploads:
            if u["type"] == "puntos":
                metadata = json.loads(u["metadata"])
                for d in metadata.get("presale_dates", [u["detected_start_date"]]):
                    point_days.add((delivery_for_presale(d).isoformat(), u["branch"]))
        work = {(w["date"], w["branch"]): w for w in self.store.workdays(key)}
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
                elif (iso, branch) in point_days:
                    state = "CARGADO"
                elif day >= self.now():
                    state = "TODAVÍA NO CORRESPONDE"
                else:
                    state = "PENDIENTE"
                branches[branch] = state
                if state == "PENDIENTE":
                    missing.append(f"Puntos {branch}")
            not_worked = not sunday and all(not work[(iso, b)]["worked"] for b in BRANCHES)
            reports = {
                "pedidos": any(u["type"] == "pedidos" and u["coverage_start"] <= iso <= u["coverage_end"] for u in uploads),
                "porcliente": any(u["type"] == "porcliente" for u in uploads),
            }
            if not not_worked:
                missing.extend(kind for kind, present in reports.items() if not present and day < self.now())
            points_ready = sunday or all(branches[b] in {"CARGADO", "NO SE TRABAJÓ"} for b in BRANCHES)
            commercial = not_worked or (points_ready and all(reports.values()))
            if not_worked:
                state = "NO_TRABAJADA"
            elif day > self.now():
                state = "FUTURA"
            elif day == self.now():
                state = "EN_CURSO"
            elif not commercial:
                state = "PREVENTA_PENDIENTE"
            else:
                state = "PREVENTA_COMPLETA"
            days.append({"date": iso, "name": DAY_NAMES[day.weekday()], "sunday": sunday,
                         "presale_date": None if sunday else presale_for_delivery(day).isoformat(),
                         "branches": branches, "reports": reports, "commercial_complete": commercial,
                         "state": state, "missing": missing, "no_work": not_worked,
                         "reasons": {b: work[(iso, b)]["reason"] for b in BRANCHES}})
        documentation_complete = all(d["commercial_complete"] for d in days)
        commercial_complete = documentation_complete and self.now().isoformat() > week["end_date"]
        status = week["status"]
        if status not in {"CERRADA", "REABIERTA"}:
            status = "LISTA_PARA_CERRAR" if commercial_complete else "EN_CURSO"
        return {"week": week, "days": days, "status": status, "commercial_complete": commercial_complete,
                "documentation_complete": documentation_complete,
                "returns_pending": sum(r["decision"] == "PENDIENTE" for r in self.store.returns(key))}

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
        lines.append("\nCierre comercial: " + ("completo" if progress["commercial_complete"] else
                     "pendiente de datos y/o jornadas aún no finalizadas"))
        lines.append(f"Devoluciones sin match pendientes: {progress['returns_pending']}")
        return "\n".join(lines)

    def build_session(self, key):
        week = self.store.week(key)
        cache_key = (key, week["revision"], self.now(), tuple(sorted(self.store.default_exclusions())))
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
        physical_uploads = [u for u in uploads if u["type"] == "pedidos"]
        for upload in uploads:
            if upload["type"] != "puntos":
                continue
            branch = upload["branch"]
            df = load_points_file(upload["file_path"])
            dates = parse_date_series(df["dia"])
            for index, row in df.iterrows():
                if pd.isna(dates.loc[index]):
                    continue
                day = delivery_for_presale(dates.loc[index]).isoformat()
                if (day, branch) not in work or not work[(day, branch)] or as_date(day) > self.now():
                    continue
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
        if physical_uploads:
            frames = []
            for upload in physical_uploads:
                frame = load_orders_file(upload["file_path"])
                frame = frame[frame["NÚMERO PEDIDO"].notna()].copy()
                frame["_number"] = frame["NÚMERO PEDIDO"].map(lambda v: clean_text(v).removesuffix(".0"))
                if frame["_number"].duplicated().any():
                    raise ValueError(f"Número de pedido repetido dentro de {upload['original_filename']}")
                frames.append(frame)
            df = pd.concat(frames, ignore_index=True)
            repeated = int(df["_number"].duplicated().sum())
            # Los uploads vienen ordenados por ID: la última carga actualiza cada pedido.
            df = df.drop_duplicates("_number", keep="last")
            if repeated:
                warnings.append(f"{repeated} apariciones repetidas entre reportes: se usa la última carga de cada número de pedido.")
            dates = parse_date_series(df["FECHA ENTREGA"])
            missing_seller = df["VENDEDOR DEL PEDIDO"].map(normalize_seller).eq("")
            df.loc[missing_seller, "VENDEDOR DEL PEDIDO"] = "SIN ASIGNAR"
            for day in week_days(week["start_date"]):
                if day <= self.now():
                    orders.extend(build_logical_orders(df.loc[dates.eq(day)], {}, day, date_column="FECHA ENTREGA"))
            selected = dates.notna() & dates.map(lambda d: False if pd.isna(d) else
                week["start_date"] <= d.isoformat() <= week["end_date"] and d <= self.now())
            excluded_orders = [{"number": clean_text(r["NÚMERO PEDIDO"]), "reason": "Entrega fuera de la semana o fecha inválida/futura",
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
        excluded = sellers & self.store.default_exclusions()
        if prior:
            payload = json.loads(prior["payload"])
            excluded = set(payload["excluded_sellers"]) | {s for s in excluded if s not in payload["sellers"]}
            assignments = {o["logical_id"]: o["assigned_seller"] for o in payload["orders"]} if payload.get("calculation_version") == 3 else {}
            for order in orders:
                order.assigned_seller = assignments.get(order.logical_id, order.original_seller)
                sellers.add(order.assigned_seller)
            if prior["source_revision"] != week["revision"] or payload.get("calculation_version") != 3:
                warnings.append("Hay cambios desde la revisión confirmada. Revisá y confirmá nuevamente antes del cierre.")
        else:
            warnings.append("Asignaciones preliminares: revisión semanal aún no confirmada.")
        for order in orders:
            if order.assigned_seller == "SIN ASIGNAR" and not order.fully_annulled:
                warnings.append(f"Pedido(s) {', '.join(order.order_numbers)}: sin vendedor en el Excel. "
                                f"Importe {order.valid_total:.2f} pendiente de asignar en Revisión; todavía no suma a los vendedores.")
        session = ReviewSession(self.store.folder(key), sorted(sellers), orders, excluded,
                                f"{week['start_date']} – {week['end_date']}", warnings, excluded_orders)
        # Adjunta únicamente las líneas atribuibles a una jornada. El resto se calcula una vez a nivel semanal.
        article_orders, return_rows, article_warnings = self.article_orders(key, session)
        self._return_cache[(key, week["revision"])] = deepcopy(return_rows)
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
            return [], [], ["PorCliente pendiente: venta disponible, artículos/proveedores todavía incompletos."]
        frame = load_porcliente_file(upload["file_path"])
        frame = frame[frame["Cod. Cliente"].notna() & frame["Código"].notna()].copy()
        from app.returns import reconcile
        week = self.store.week(key)
        carriers, rows, warnings = reconcile(frame, session, week, self.store.returns(key))
        self.store.sync_returns(key, rows)
        carriers, rows, warnings = reconcile(frame, session, week, self.store.returns(key))
        pending = sum(r["decision"] == "PENDIENTE" for r in rows)
        if pending:
            warnings.append(f"Hay {pending} devoluciones pendientes de aprobar/rechazar.")
        return carriers, rows, warnings

    def confirm_review(self, key, session, revision):
        if any(o.assigned_seller not in session.sellers or o.assigned_seller == "SIN ASIGNAR"
               for o in session.orders if not o.fully_annulled):
            raise ValueError("Asigná todos los pedidos válidos antes de confirmar")
        payload = review_snapshot(session)
        payload["confirmed_at"] = timestamp()
        payload["date_basis"] = "delivery"
        payload["calculation_version"] = 3
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
        return_rows = deepcopy(self._return_cache.get((key, revision), []))
        progress = self.progress(key)
        included = [s for s in session.sellers if s not in session.excluded_sellers and s != "SIN ASIGNAR"]
        orders = [o for o in session.orders if not o.fully_annulled and o.assigned_seller in included]
        article_orders = [o for o in carriers if o.assigned_seller in included]
        active_types = {u["type"] for u in self.store.uploads(key, active=True)}
        completed_days = {d["date"] for d in progress["days"] if d["commercial_complete"]
                          and not d["no_work"] and not d["sunday"] and as_date(d["date"]) < self.now()}

        def summarize(selected, article_selected, selected_sellers):
            sale = sum(o.valid_total for o in selected)
            article_net = defaultdict(float)
            article_day_net = defaultdict(float)
            for order in article_selected:
                for article in order.articles:
                    value = article.net_total if article.net_total is not None else article.total
                    article_net[order.client_code] += value
                    article_day_net[(order.preventa_day, order.client_code)] += value
            has_porcliente = "porcliente" in active_types
            buyers = ({client for client, value in article_net.items() if value > .005} if has_porcliente
                      else {o.client_code for o in selected})
            sale_net = round(sum(article_net.values()), 2) if has_porcliente else (
                None if any(o.net_total is None for o in selected) else round(sum(o.net_total for o in selected), 2))
            sale_gross = round(sum((a.net_total if a.net_total is not None else a.total)
                for o in article_selected for a in o.articles if (a.net_total if a.net_total is not None else a.total) > 0), 2) if has_porcliente else sale_net
            returns_total = round(abs(sum((a.net_total if a.net_total is not None else a.total)
                for o in article_selected for a in o.articles if (a.net_total if a.net_total is not None else a.total) < 0)), 2) if has_porcliente else 0
            assigned, visited, working_dates = set(), set(), set()
            operational_buyers = set()
            for seller in selected_sellers:
                act = activity.get(seller, {"assigned": set(), "visited": set(), "days": set()})
                assigned.update(act["assigned"])
                visited.update(act["visited"])
                working_dates.update(act["days"] & completed_days)
                operational_buyers.update(act["visited"] & {pair for pair, value in article_day_net.items() if value > .005})
            articles = aggregate_articles(article_selected, len(buyers), sale)
            providers = aggregate_providers(articles, sale, len(buyers))
            mix_pairs = {(client, a["code"]) for a in articles for client in a.get("client_codes", [])}
            operational_sale = (sum(value for (day, _), value in article_day_net.items() if day in working_dates)
                                if has_porcliente else sum(o.valid_total for o in selected if o.preventa_day in working_dates))
            return {"sale": round(sale, 2), "sale_gross": sale_gross, "returns": returns_total, "sale_net": sale_net,
                    "average_ticket_net": round(sale_net / len(buyers), 2) if buyers and sale_net is not None else None,
                    "reward_availability": {"orders": "pedidos" in active_types, "articles": "porcliente" in active_types,
                                            "sigo": bool(assigned)}, "buyers": len(buyers), "assigned_clients": len(assigned),
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
            values.update(seller=seller, company_share_pct=0)
            sellers.append(values)
        net_total_for_share = sum(s["sale_net"] or 0 for s in sellers)
        for values in sellers:
            values["company_share_pct"] = round(percentage(values["sale_net"] or 0, net_total_for_share), 2)
        company = summarize(orders, article_orders, included)
        articles, providers = company.pop("articles"), company.pop("providers")
        company.update(included_sellers=len(included), excluded_sellers=len(session.excluded_sellers),
                       original_sale=round(sum(o.original_total for o in session.orders if o.assigned_seller in included), 2))
        active = self.store.uploads(key, active=True)
        pedidos = max((u for u in active if u["type"] == "pedidos"), key=lambda u: u["coverage_end"], default=None)
        porcliente = next((u for u in active if u["type"] == "porcliente"), None)
        data_until = min(pedidos["coverage_end"], self.now().isoformat()) if pedidos and pedidos["coverage_start"] <= self.now().isoformat() else None
        articles_until = min(porcliente["coverage_end"], self.now().isoformat()) if porcliente and porcliente["coverage_start"] <= self.now().isoformat() else None
        complete_until = None
        for d in progress["days"]:
            if not d["commercial_complete"] or as_date(d["date"]) >= self.now():
                break
            complete_until = d["date"]
        sunday_orders = [o for o in orders if as_date(o.preventa_day).weekday() == 6]
        result = {"schema_version": 4, "week_id": key, "preventa_date": session.preventa_date,
                  "status": progress["status"], "final_numbers": False,
                  "processed_at": timestamp(), "source_revision": revision, "date_basis": "delivery", "calculation_version": 3,
                  "data_until": data_until, "commercial_complete": progress["commercial_complete"],
                  "articles_until": articles_until, "complete_until": complete_until,
                  "company": company, "sellers": sorted(sellers, key=lambda s: s["sale"], reverse=True),
                  "articles": articles, "providers": providers, "warnings": session.warnings,
                  "returns": return_rows,
                  "review": review_snapshot(session), "active_upload_ids": [u["id"] for u in active],
                  "article_attributions": [asdict(o) for o in carriers],
                  "daily_activity": [{"seller": s, "delivery_date": d, "presale_date": presale_for_delivery(d).isoformat(),
                      "assigned": len({c for day, c in act["assigned"] if day == d}),
                      "visited": len({c for day, c in act["visited"] if day == d}),
                      "sold_sigo": len({c for day, c in act["sale_signal"] if day == d})}
                      for s, act in activity.items() if s in included for d in sorted(act["days"])],
                  "activity": {s: {name: sorted(entries) for name, entries in metrics.items()} for s, metrics in activity.items()},
                  "sunday": {"sale": round(sum(o.valid_total for o in sunday_orders), 2),
                             "logical_orders": len({(o.client_code, o.assigned_seller) for o in sunday_orders})},
                  "metric_basis": "Cobertura y conversión: pares cliente/jornada con SIGO activo. Domingo excluido. Promedio operativo: jornadas comerciales completas con actividad, sin domingo."}
        result["daily_totals"] = []
        for d in sorted({d for seller, act in activity.items() if seller in included for d in act["days"]}):
            row = {"seller": "TOTAL EMPRESA", "delivery_date": d, "presale_date": presale_for_delivery(d).isoformat()}
            for field, source in [("assigned", "assigned"), ("visited", "visited"), ("sold_sigo", "sale_signal")]:
                row[field] = len({c for seller, act in activity.items() if seller in included for day, c in act[source] if day == d})
            result["daily_totals"].append(row)
        return result

    def process(self, key):
        data = self.metrics(key)
        if self.store.week(key)["status"] != "CERRADA":
            from app.rewards import RewardService
            data["awards"] = RewardService(self).calculate(key, data)
            self.store.save_snapshot(key, data)
        return data

    def decide_return(self, key, fingerprint, decision, note=""):
        self.decide_returns(key, [fingerprint], decision, note)

    def decide_returns(self, key, fingerprints, decision, note=""):
        self.store.decide_returns(key, fingerprints, decision, note)
        self._cache.clear()
        self._return_cache.clear()

    def export_path(self, path, suffix=".json"):
        target = Path(path).resolve()
        repo = Path(__file__).resolve().parents[1]
        history = (self.store.root / "HISTORIAL").resolve()
        if repo == target or repo in target.parents or history == target or history in target.parents:
            raise ValueError("Exportá fuera del repositorio y del historial protegido")
        if target.suffix.lower() != suffix:
            raise ValueError(f"La exportación debe tener extensión {suffix}")
        return target

    def export(self, key, path):
        data = self.metrics(key)
        if self.store.week(key)["status"] != "CERRADA":
            from app.rewards import RewardService
            data["awards"] = RewardService(self).calculate(key, data)
        return write_json(self.export_path(path), data)

    def close(self, key, exception_reason=""):
        progress = self.progress(key)
        if not progress["documentation_complete"]:
            raise ValueError("Faltan datos comerciales para cerrar la semana")
        exceptional = self.now().isoformat() <= progress["week"]["end_date"]
        if exceptional and not exception_reason.strip():
            raise ValueError("La semana todavía no terminó; indicá un motivo para el cierre excepcional")
        review = self.store.latest_review(key)
        if (review is None or review["source_revision"] != self.store.week(key)["revision"]
                or json.loads(review["payload"]).get("calculation_version") != 3):
            raise ValueError("Confirmá la revisión de las versiones activas antes del cierre")
        data = self.metrics(key)
        pending = [r for r in data.get("returns", []) if r["decision"] == "PENDIENTE"]
        if pending:
            raise ValueError(f"Hay {len(pending)} devoluciones pendientes de aprobar/rechazar")
        from app.rewards import RewardService
        awards = RewardService(self).closing(key, data)
        data.update(status="CERRADA", closed_at=timestamp(), administrative_closed=True, final_numbers=True, awards=awards,
                    exceptional_close={"used": exceptional, "reason": exception_reason.strip() if exceptional else ""})
        return self.store.save_snapshot(key, data, kind="cierre", close=True)
