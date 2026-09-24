"""Conciliación simple de devoluciones de PorCliente con ventas de la semana."""
from collections import defaultdict
from copy import deepcopy
from datetime import date
import hashlib
import json

import pandas as pd

from app.importers import parse_date_series
from app.review_data import (ArticleLine, LogicalOrder, clean_text, normalize_seller,
                             normalize_text, safe_float)


def return_summary(rows, included_sellers):
    """Amounts received versus effective company deductions; groups may overlap."""
    groups = [("Total", lambda r: True),
              ("Con match", lambda r: r["matched"]),
              ("Sin match", lambda r: not r["matched"])]
    groups += [(label, lambda r, state=state: r["decision"] == state)
               for label, state in [("Automáticas", "AUTOMATICA"), ("Aprobadas", "APROBADA"),
                                    ("Rechazadas", "RECHAZADA"), ("Pendientes", "PENDIENTE"),
                                    ("Ignoradas", "IGNORADA")]]
    return [dict(label=label, count=len(selected),
                 amount=round(sum(abs(r["amount_net"]) for r in selected), 2),
                 applied=round(sum(max(0, -r["impact"]) for r in selected
                                   if r["assigned_seller"] in included_sellers), 2))
            for label, predicate in groups for selected in [[r for r in rows if predicate(r)]]]


def code(value):
    return clean_text(value).removesuffix(".0")


def plain_date(value):
    return value.date() if hasattr(value, "date") else value


def fingerprint(row, occurrence=0):
    """Huella independiente del número de fila; occurrence distingue duplicados idénticos."""
    stable = [row.get(k, "") for k in ("date", "client", "source_seller", "article",
                                        "provider", "quantity", "amount_net")]
    raw = json.dumps(stable + [occurrence], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reconcile(frame, session, week, saved=()):
    """Devuelve carriers neteados, movimientos y advertencias.

    Las ventas nacen solo de positivos asociados por cliente+fecha a un pedido de
    la semana. Un negativo posterior puede usar esas ventas como antecedente.
    """
    frame = frame.copy()
    frame["_date"] = parse_date_series(frame["Descripción Período"])
    frame["_net"] = frame["Importes Netos"].map(safe_float)
    frame["_qty"] = frame["Cantidades Totales"].map(safe_float)
    orders = [o for o in session.orders if not o.fully_annulled]
    order_index = defaultdict(list)
    seller_index = defaultdict(list)
    for order in orders:
        order_index[(order.client_code, order.preventa_day)].append(order)
        if order.assigned_seller != "SIN ASIGNAR":
            seller_index[(order.client_code, order.original_seller)].append(order)
    positives, warnings = [], []
    carriers = {}

    def destinations(client, day):
        return order_index.get((client, day), ())

    for raw in frame.loc[frame["_net"] > 0].to_dict("records"):
        if pd.isna(raw["_date"]):
            continue
        day, client = plain_date(raw["_date"]).isoformat(), code(raw.get("Cod. Cliente"))
        matches = destinations(client, day)
        finals = {o.assigned_seller for o in matches if o.assigned_seller != "SIN ASIGNAR"}
        if not matches or len(finals) != 1:
            # Positivos fuera de semana o ambiguos nunca se incorporan por su propia fecha.
            if matches:
                warnings.append(f"Artículos pendientes de atribución: cliente {client}, fecha {day}, con distintos vendedores finales.")
            continue
        order = matches[0]
        assigned = next(iter(finals))
        provider = normalize_text(raw.get("Descripción.5"))
        item = dict(date=day, client=client, source_seller=normalize_seller(raw.get("Descripción Vendedor")),
                    assigned_seller=assigned, article=code(raw.get("Código")),
                    description=clean_text(raw.get("Descripción.2")), provider=provider,
                    quantity=float(raw["_qty"]), amount_net=float(raw["_net"]),
                    amount_final=safe_float(raw.get("Importes Finales")), order=order,
                    remaining=float(raw["_net"]))
        positives.append(item)
        carrier_key = (assigned, client, day)
        if carrier_key not in carriers:
            carrier = deepcopy(order)
            carrier.logical_id = order.logical_id if len(matches) == 1 else f"articles:{assigned}:{client}:{day}"
            carrier.articles = []
            carriers[carrier_key] = carrier
        carriers[carrier_key].articles.append(ArticleLine(item["article"], item["description"], provider,
            item["quantity"], safe_float(raw.get("Bonific")), item["amount_final"], item["amount_net"]))

    positive_index = defaultdict(list)
    for item in positives:
        positive_index[(item["client"], item["article"], item["source_seller"])].append(item)
    for values in positive_index.values():
        values.sort(key=lambda item: item["date"], reverse=True)
    saved_by_fp = {r["fingerprint"]: r for r in saved}
    occurrences, movements = defaultdict(int), []
    negatives = frame.loc[frame["_net"] < 0].sort_values("_date", kind="stable")
    for raw in negatives.to_dict("records"):
        if pd.isna(raw["_date"]):
            continue
        day = plain_date(raw["_date"]).isoformat()
        base = dict(date=day, client=code(raw.get("Cod. Cliente")),
                    source_seller=normalize_seller(raw.get("Descripción Vendedor")),
                    article=code(raw.get("Código")), description=clean_text(raw.get("Descripción.2")),
                    provider=normalize_text(raw.get("Descripción.5")), quantity=float(raw["_qty"]),
                    amount_net=float(raw["_net"]), amount_final=safe_float(raw.get("Importes Finales")))
        identity = tuple(base.values())
        occurrence = occurrences[identity]
        occurrences[identity] += 1
        base["fingerprint"] = fingerprint(base, occurrence)
        candidates = positive_index.get((base["client"], base["article"], base["source_seller"]), ())
        match = next((p for p in candidates if p["date"] <= day and p["remaining"] > .005), None)
        requested = abs(base["amount_net"])
        automatic = min(requested, match["remaining"]) if match else 0.0
        if match:
            match["remaining"] -= automatic
        excess = round(requested - automatic, 2)
        outside = (day < week["start_date"] or day > week["end_date"]) and match is None
        persisted = saved_by_fp.get(base["fingerprint"])
        decision = persisted["decision"] if persisted else (
            "AUTOMATICA" if match and not excess else "IGNORADA" if outside else "PENDIENTE")
        impact = automatic + (excess if decision == "APROBADA" else 0.0)
        assigned = match["assigned_seller"] if match else ""
        if not assigned and not outside:
            possible = seller_index.get((base["client"], base["source_seller"]), ())
            if possible:
                assigned = min(possible, key=lambda o: abs((date.fromisoformat(o.preventa_day) - plain_date(raw["_date"])).days)).assigned_seller
            else:
                assigned = base["source_seller"]
        movement = dict(base, matched=bool(match), matched_sale_ref=(match["order"].logical_id if match else ""),
                        assigned_seller=assigned, automatic_amount=round(automatic, 2), excess=excess,
                        outside_unmatched=outside, decision=decision, note=persisted["note"] if persisted else "",
                        impact=round(-impact, 2), warning="Devolución mayor que la venta conciliada" if match and excess else "")
        movements.append(movement)
        if impact <= 0 or not assigned:
            continue
        ratio = impact / requested if requested else 0
        quantity = -abs(base["quantity"]) * ratio
        target_day = match["date"] if match else max(week["start_date"], min(day, week["end_date"]))
        carrier_key = (assigned, base["client"], target_day)
        if carrier_key not in carriers:
            template = match["order"] if match else next((o for o in orders if o.assigned_seller == assigned), None)
            carrier = deepcopy(template) if template else LogicalOrder(
                f"return:{assigned}:{base['client']}:{target_day}", base["client"], "", assigned, assigned)
            carrier.logical_id = f"returns:{assigned}:{base['client']}:{target_day}"
            carrier.preventa_day = target_day
            carrier.articles = []
            carriers[carrier_key] = carrier
        carriers[carrier_key].articles.append(ArticleLine(base["article"], base["description"], base["provider"],
            quantity, 0, base["amount_final"] * ratio, -impact))
        if movement["warning"]:
            warnings.append(movement["warning"] + f": {base['client']} / {base['article']} / {day}.")
    return list(carriers.values()), movements, warnings
