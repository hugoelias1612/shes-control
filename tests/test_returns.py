"""Devoluciones semanales derivadas de PorCliente."""
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from app.rewards import RewardService
from app.week_calendar import BRANCHES, presale_for_delivery
from app.week_imports import inspect_upload
from app.week_service import WeekService
from app.week_store import WeekStore
from test_presale import article, physical, point

MON = date(2026, 9, 7)


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = WeekStore(self.root / "data")
        self.key = self.store.ensure_week(MON)["id"]
        self.service = WeekService(self.store, today=date(2026, 9, 20)); self.serial = 0

    def excel(self, rows):
        self.serial += 1; path = self.root / f"file_{self.serial}.xlsx"
        pd.DataFrame(rows).to_excel(path, index=False); return path

    def order(self, number, day, seller="A", client=1, total=100):
        return physical(number, seller, client, total, **{"FECHA ENTREGA": day.strftime("%d/%m/%Y"),
            "NETO GRAVADO": total, "NO GRAVADO": 0})

    def line(self, day, amount, code=10, seller="A", client=1, quantity=None, provider="GAONA"):
        row = article(client, seller, code, amount, provider)
        row["Descripción Período"] = day.strftime("%d/%m/%Y")
        row["Importes Netos"] = amount; row["Importes Finales"] = amount
        row["Cantidades Totales"] = quantity if quantity is not None else (1 if amount > 0 else -1)
        return row

    def candidate(self, rows, kind_range=None):
        candidate = inspect_upload(self.excel(rows))
        candidate.metadata["coverage_confirmed"] = True
        if candidate.kind == "pedidos":
            candidate.coverage_start, candidate.coverage_end = MON.isoformat(), (MON + timedelta(days=6)).isoformat()
        elif kind_range:
            candidate.coverage_start, candidate.coverage_end = (d.isoformat() for d in kind_range)
        return candidate

    def upload(self, *candidates):
        return self.store.commit_uploads(self.key, candidates, self.store.week(self.key)["revision"])

    def load(self, orders, lines):
        self.upload(self.candidate(orders), self.candidate(lines, (MON, MON + timedelta(days=9))))
        return self.service.metrics(self.key)

    def confirm_review(self):
        session, _, _, revision = self.service.build_session(self.key)
        self.service.confirm_review(self.key, session, revision)

    def test_wide_porcliente_filters_late_positive_and_uses_late_return(self):
        sold = MON + timedelta(days=3)
        data = self.load([self.order(1, sold)], [self.line(sold, 100, quantity=1),
            self.line(MON + timedelta(days=8), 999, code=20),
            self.line(MON + timedelta(days=8), -40, quantity=-.4),
            self.line(MON + timedelta(days=9), -70, code=30, quantity=-.7)])
        self.assertEqual(data["company"]["sale_gross"], 100)
        self.assertEqual(data["company"]["returns"], 40)
        self.assertEqual(data["company"]["sale_net"], 60)
        seller = next(s for s in data["sellers"] if s["seller"] == "A")
        self.assertEqual((seller["sale_gross"], seller["returns"], seller["sale_net"]), (100, 40, 60))
        self.assertEqual((data["articles"][0]["sale_net"], data["providers"][0]["sale_net"]), (60, 60))
        self.assertNotIn("20", {a["code"] for a in data["articles"]})
        ignored = next(r for r in data["returns"] if r["article"] == "30")
        self.assertEqual(ignored["decision"], "IGNORADA")
        self.assertEqual(ignored["impact"], 0)

    def test_partial_and_total_return_recalculate_buyers_conversion_but_not_coverage(self):
        day = MON + timedelta(days=2)
        p = point(1, "A", 1); p["dia"] = presale_for_delivery(day).strftime("%d/%m/%Y")
        pc = self.candidate([p]); pc.branch = "corrientes"
        self.upload(pc, self.candidate([self.order(1, day)]), self.candidate([
            self.line(day, 100, quantity=1), self.line(day + timedelta(days=1), -40, quantity=-.4)]))
        partial = self.service.metrics(self.key)
        self.assertEqual((partial["company"]["sale_net"], partial["company"]["buyers"]), (60, 1))
        self.assertEqual(partial["company"]["average_ticket_net"], 60)
        self.assertEqual((partial["company"]["coverage_pct"], partial["company"]["conversion_pct"]), (100, 100))
        self.upload(self.candidate([self.line(day, 100, quantity=1), self.line(MON + timedelta(days=8), -100, quantity=-1)]))
        total = self.service.metrics(self.key)
        self.assertEqual((total["company"]["sale_net"], total["company"]["buyers"]), (0, 0))
        self.assertEqual((total["company"]["coverage_pct"], total["company"]["conversion_pct"]), (100, 0))
        self.assertEqual(total["articles"][0]["quantity"], 0)

    def test_nearest_prior_sale_and_reassignment(self):
        first, second, returned = MON, MON + timedelta(days=2), MON + timedelta(days=4)
        self.load([self.order(1, first), self.order(2, second)], [self.line(first, 50), self.line(second, 60), self.line(returned, -20)])
        session, _, _, revision = self.service.build_session(self.key)
        for order in session.orders: order.assigned_seller = "B"
        session.sellers.append("B"); self.service.confirm_review(self.key, session, revision)
        data = self.service.metrics(self.key); movement = data["returns"][0]
        self.assertIn(second.isoformat(), movement["matched_sale_ref"])
        self.assertEqual(movement["assigned_seller"], "B")
        self.assertEqual(next(s for s in data["sellers"] if s["seller"] == "B")["sale_net"], 90)

    def test_unmatched_decision_persists_and_controls_impact(self):
        data = self.load([self.order(1, MON)], [self.line(MON, -30, code=99)])
        movement = data["returns"][0]
        self.assertEqual(movement["decision"], "PENDIENTE")
        self.assertEqual(data["company"]["returns"], 0)
        self.service.decide_return(self.key, movement["fingerprint"], "APROBADA", "Mercadería verificada")
        approved = self.service.metrics(self.key)
        self.assertEqual((approved["company"]["returns"], approved["company"]["sale_net"]), (30, -30))
        self.upload(self.candidate([self.line(MON, -30, code=99)]))
        reimported = self.service.metrics(self.key)
        self.assertEqual(len(reimported["returns"]), 1)
        self.assertEqual(reimported["returns"][0]["decision"], "APROBADA")
        self.service.decide_return(self.key, movement["fingerprint"], "RECHAZADA", "No corresponde")
        rejected = self.service.metrics(self.key)
        self.assertEqual((rejected["company"]["returns"], rejected["company"]["sale_net"]), (0, 0))

    def test_preweek_unmatched_is_ignored_and_pending_rows_allow_bulk_decision(self):
        data = self.load([self.order(1, MON)], [self.line(MON - timedelta(days=2), -10, code=97),
            self.line(MON, -20, code=98), self.line(MON + timedelta(days=1), -30, code=99)])
        old = next(r for r in data["returns"] if r["article"] == "97")
        self.assertEqual((old["decision"], old["impact"]), ("IGNORADA", 0))
        pending = [r for r in data["returns"] if r["decision"] == "PENDIENTE"]
        self.assertEqual(len(pending), 2)
        self.service.decide_returns(self.key, [r["fingerprint"] for r in pending], "RECHAZADA", "Fuera del control")
        recalculated = self.service.metrics(self.key)
        self.assertTrue(all(r["decision"] == "RECHAZADA" for r in recalculated["returns"] if r["article"] in {"98", "99"}))
        audits = self.store.query("SELECT details FROM audit_events WHERE action='rechazar_devolucion'")
        self.assertEqual(len(audits), 2)

    def test_return_larger_than_sale_applies_match_and_leaves_excess_pending(self):
        data = self.load([self.order(1, MON)], [self.line(MON, 20, quantity=1), self.line(MON + timedelta(days=1), -30, quantity=-1.5)])
        movement = data["returns"][0]
        self.assertEqual((movement["automatic_amount"], movement["excess"], movement["impact"]), (20, 10, -20))
        self.assertEqual(movement["decision"], "PENDIENTE")
        self.assertIn("mayor", movement["warning"])
        self.service.decide_return(self.key, movement["fingerprint"], "APROBADA")
        self.assertEqual(self.service.metrics(self.key)["company"]["sale_net"], -10)

    def test_commission_and_reward_use_net_after_return(self):
        data = self.load([self.order(1, MON)], [self.line(MON, 100), self.line(MON + timedelta(days=1), -30, quantity=-.3)])
        engine = RewardService(self.service)
        engine.save_rule(dict(name="Nivel", metric="sale_net", operator=">=", target=80, amount=10,
                              date_from=MON.isoformat(), active=True, scope=[]))
        awards = engine.calculate(self.key, self.service.metrics(self.key))
        seller = next(s for s in awards["sellers"] if s["seller"] == "A")
        self.assertEqual(seller["sale_net"], 70)
        self.assertEqual(seller["base_commission"], 2.1)
        self.assertEqual(seller["total_awards"], 0)

    def test_close_blocks_pending_and_allows_resolved_without_liquidations(self):
        self.load([self.order(1, MON)], [self.line(MON, -20, code=99)])
        for offset in range(0, 6):
            self.store.set_worked(self.key, MON + timedelta(days=offset), BRANCHES, False, "Prueba")
        self.confirm_review()
        with self.assertRaisesRegex(ValueError, "devoluciones pendientes"):
            self.service.close(self.key)
        movement = self.service.metrics(self.key)["returns"][0]
        self.service.decide_return(self.key, movement["fingerprint"], "RECHAZADA")
        self.service.close(self.key)
        self.assertEqual(self.store.week(self.key)["status"], "CERRADA")

    def test_exceptional_close_requires_and_snapshots_reason(self):
        self.load([self.order(1, MON)], [self.line(MON, 100)])
        for offset in range(6):
            self.store.set_worked(self.key, MON + timedelta(days=offset), BRANCHES, False, "Prueba")
        self.confirm_review(); self.service.today = MON + timedelta(days=2)
        with self.assertRaisesRegex(ValueError, "motivo"):
            self.service.close(self.key)
        path = self.service.close(self.key, "Cierre autorizado para prueba")
        import json
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["exceptional_close"], {"used": True, "reason": "Cierre autorizado para prueba"})


if __name__ == "__main__":
    unittest.main()
