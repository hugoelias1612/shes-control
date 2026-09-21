import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.history import save_raw_load
from app.importers import PEDIDOS_REQUIRED_COLUMNS, PORCLIENTE_REQUIRED_COLUMNS, validate_puntos
from app.review_data import (build_review_session, build_logical_orders, save_review,
                             safe_float, is_yes)
from app.processor import process_presale
from app.storage import write_json


def physical(number, seller, client, total, day="18/09/2026", **flags):
    row = dict.fromkeys(PEDIDOS_REQUIRED_COLUMNS, "")
    row.update({"NÚMERO PEDIDO": number, "VENDEDOR DEL PEDIDO": seller,
                "CLIENTE": f"{client} - Cliente ficticio", "TOTAL": total,
                "FECHA/HORA DE ALTA": day + " 09:00", "FECHA ENTREGA": "19/09/2026"})
    row.update(flags)
    return row


def article(client, seller, code, amount, provider="GAONA"):
    row = dict.fromkeys(PORCLIENTE_REQUIRED_COLUMNS, "")
    row.update({"Descripción Período": "19/09/2026", "Cod. Cliente": client,
                "Descripción Vendedor": seller, "Código": code,
                "Descripción.2": f"Artículo {code}", "Descripción.5": provider,
                "Descripción.3": "MARCA NO PROVEEDOR", "Cantidades Totales": 0.5,
                "Importes Finales": amount, "Importes Netos": amount})
    return row


def point(client, seller, visited=0, hour=""):
    return {"idcliente": client + 1000, "CodClienteEmpresa": client,
            "nomcli": "Cliente ficticio", "ruta": 1, "dia": "18/09/2026",
            "c_vendedor": 1, "d_perso": seller, "visitado": visited, "horaVenta": hour}


class PresaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.points = pd.DataFrame([point(1, "A", 1.0, "09:00"), point(2, "A"),
                                    point(3, "CERO"), point(4, "HUGO")])
        self.points.to_excel(self.folder / "puntos_ctes.xlsx", index=False, startrow=2)
        pd.DataFrame([point(1, "B"), point(5, "B", 1)]).to_excel(
            self.folder / "puntos_resistencia.xlsx", index=False)
        self.rows = [physical(1, "A", 1, 100), physical(2, "A", 1, 50),
                     physical(3, "A", 1, 25, ANULADO="SÍ"),
                     physical(4, "A", 2, 50, FACTURADO="SI"),
                     physical(5, "B", 1, 75), physical(6, "HUGO", 4, 1000),
                     physical(7, "A", 99, 9999, day="17/09/2026"),
                     physical(8, "A", 98, 123, ANULADO="SI")]
        pd.DataFrame(self.rows).to_excel(self.folder / "reporte_pedidos.xlsx", index=False)
        pd.DataFrame([article(1, "A", 10, 100), article(1, "A", 20, 50),
                      article(2, "A", 20, 50), article(1, "B", 30, 75),
                      article(4, "HUGO", 40, 1000)]).to_excel(self.folder / "porcliente.xlsx", index=False)
        self.session = build_review_session(self.folder)

    def process(self):
        save_review(self.session)
        return process_presale(self.session)

    def test_date_consolidation_annulled_pending(self):
        orders = self.session.orders
        a1 = next(o for o in orders if o.original_seller == "A" and o.client_code == "1")
        self.assertEqual(a1.original_total, 175)
        self.assertEqual(a1.valid_total, 150)
        self.assertEqual(a1.status, "MIXTO")
        self.assertEqual(len(a1.order_numbers), 3)
        self.assertNotIn("99", {o.client_code for o in orders})
        self.assertEqual(len(self.session.excluded_orders), 1)
        self.assertEqual(self.session.excluded_sellers, {"HUGO"})
        self.assertEqual(self.process()["company"]["sale"], 275)

    def test_reassignment_unites_orders_and_moves_articles_only(self):
        next(o for o in self.session.orders if o.original_seller == "A" and o.client_code == "1").assigned_seller = "B"
        data = self.process()
        sellers = {s["seller"]: s for s in data["sellers"]}
        self.assertEqual(sellers["B"]["sale"], 225)
        self.assertEqual(sellers["B"]["logical_orders"], 1)
        self.assertEqual(sellers["B"]["average_ticket"], 225)
        self.assertEqual(sellers["B"]["buyers"], 1)
        self.assertEqual(len(sellers["B"]["articles"]), 3)
        self.assertEqual(self.session.current_order_count("B"), 1)
        self.assertEqual(sellers["A"]["visited_clients"], 1)
        self.assertEqual(sellers["A"]["assigned_clients"], 2)
        self.assertEqual(data["company"]["logical_orders"], 2)

    def test_provider_actual_union_and_company_unique_clients(self):
        data = self.process()
        self.assertEqual(data["providers"][0]["clients"], 2)
        a = next(s for s in data["sellers"] if s["seller"] == "A")
        self.assertEqual(a["providers"][0]["clients"], 2)
        self.assertEqual(a["providers"][0]["provider"], "GAONA")
        self.assertEqual(a["coverage_pct"], 50)
        self.assertEqual(a["average_ticket"], 100)
        self.assertEqual(data["company"]["buyers"], 2)
        self.assertEqual(data["company"]["assigned_clients"], 4)
        self.assertEqual(data["company"]["average_ticket"], 137.5)

    def test_provider_disjoint_and_overlapping_buyers(self):
        from app.processor import aggregate_providers
        articles = [dict(provider="GAONA", code="1", sale=10, quantity=0.5,
                         clients=2, client_codes=["A", "B"]),
                    dict(provider="GAONA", code="2", sale=20, quantity=1,
                         clients=2, client_codes=["B", "C"])]
        provider = aggregate_providers(articles, 30, 3)[0]
        self.assertEqual(provider["clients"], 3)
        self.assertEqual(provider["buyer_coverage_pct"], 100)

    def test_zero_visits_and_excluded(self):
        self.session.excluded_sellers.add("A")
        data = self.process()
        self.assertEqual(data["company"]["sale"], 75)
        self.assertEqual({a["code"] for a in data["articles"]}, {"30"})
        zero = next(s for s in data["sellers"] if s["seller"] == "CERO")
        self.assertEqual(zero["conversion_pct"], 0)
        self.assertEqual(zero["average_ticket"], 0)

    def test_confirmation_and_json_audit(self):
        with self.assertRaises(ValueError):
            process_presale(self.session)
        data = self.process()
        self.assertFalse(data["final_numbers"])
        self.assertTrue(data["liquidations_required"])
        snapshot = json.loads((self.folder / "revision_preventa.json").read_text(encoding="utf-8"))
        self.assertIn("articles", snapshot["orders"][0])
        self.assertIn("original_seller", data["review"]["orders"][0])
        self.session.excluded_sellers.add("B")
        with self.assertRaises(ValueError):
            process_presale(self.session)

    def test_processor_defends_date(self):
        self.session.orders[0].preventa_day = "2026-09-17"
        save_review(self.session)
        with self.assertRaises(ValueError):
            process_presale(self.session)

    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            build_logical_orders(pd.DataFrame([self.rows[0], self.rows[0]]), {}, date(2026, 9, 18))

    def test_multiple_states_and_modification(self):
        rows = [physical(1, "A", 1, 10, FACTURADO="SI"),
                physical(2, "A", 1, 20, MODIFICADO="SI")]
        order = build_logical_orders(pd.DataFrame(rows), {}, date(2026, 9, 18))[0]
        self.assertEqual(order.status, "MIXTO")
        self.assertTrue(order.modified)
        self.assertEqual(order.valid_total, 30)

    def test_all_excluded(self):
        self.session.excluded_sellers = set(self.session.sellers)
        data = self.process()
        self.assertEqual(data["company"]["sale"], 0)
        self.assertEqual(data["company"]["coverage_pct"], 0)

    def test_invalid_point_date(self):
        self.points.loc[0, "dia"] = "inválido"
        self.points.to_excel(self.folder / "puntos_ctes.xlsx", index=False)
        self.assertFalse(validate_puntos(self.folder / "puntos_ctes.xlsx", "Corrientes").valid)

    def test_history_versioned_raw_unchanged(self):
        files = dict(ctes=self.folder / "puntos_ctes.xlsx", resis=self.folder / "puntos_resistencia.xlsx",
                     pedidos=self.folder / "reporte_pedidos.xlsx", porcliente=self.folder / "porcliente.xlsx")
        first = save_raw_load(self.folder / "history", date(2026, 9, 18), files)
        second = save_raw_load(self.folder / "history", date(2026, 9, 18), files)
        self.assertEqual(first.name, "carga_01")
        self.assertEqual(second.name, "carga_02")
        self.assertEqual((first / "porcliente.xlsx").read_bytes(), files["porcliente"].read_bytes())

    def test_atomic_json_preserves_previous_on_failure(self):
        target = self.folder / "test.json"
        write_json(target, {"válido": 1})
        with self.assertRaises(ValueError):
            write_json(target, {"bad": float("nan")})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"válido": 1})

    def test_numbers(self):
        self.assertTrue(is_yes(1.0))
        self.assertEqual(safe_float("$1.234,50"), 1234.5)
        with self.assertRaises(ValueError):
            safe_float("dato corrupto")

    def test_two_cent_tolerance_does_not_warn_on_float_noise(self):
        from app.review_data import build_article_map, load_porcliente_file
        articles = build_article_map(load_porcliente_file(self.folder / "porcliente.xlsx"))
        articles[("1", "A")][0].total += 0.02
        with patch("app.review_data.build_article_map", return_value=articles):
            session = build_review_session(self.folder)
        self.assertFalse(any("__A__1." in warning for warning in session.warnings))
        articles[("1", "A")][0].total += 0.01
        with patch("app.review_data.build_article_map", return_value=articles):
            session = build_review_session(self.folder)
        self.assertTrue(any("__A__1." in warning for warning in session.warnings))

    def test_mixed_date_formats(self):
        from app.importers import parse_date_series
        parsed = parse_date_series(pd.Series(["18/09/2026", "2026-09-18", pd.Timestamp("2026-09-18")]))
        self.assertTrue(parsed.eq(date(2026, 9, 18)).all())

    def test_mismatching_regions_rejected(self):
        self.points["dia"] = "17/09/2026"
        self.points.to_excel(self.folder / "puntos_ctes.xlsx", index=False)
        with self.assertRaises(ValueError):
            build_review_session(self.folder)

    def test_sale_signal_is_not_moved_or_invented(self):
        self.points.loc[2, "horaVenta"] = "10:00"
        self.points.to_excel(self.folder / "puntos_ctes.xlsx", index=False)
        data = self.process()
        self.assertEqual(data["activity"]["CERO"]["sale_signal_codes"], ["3"])
        self.assertTrue(any("Hora Venta" in warning for warning in data["warnings"]))
        self.assertEqual(next(s for s in data["sellers"] if s["seller"] == "CERO")["buyers"], 0)

    def test_direct_ui_imports_load_pandas_first(self):
        for module in ["app.review_window", "app.dashboard_window", "main"]:
            result = subprocess.run([sys.executable, "-c",
                f"import {module}; import sys; m=list(sys.modules); assert m.index('pandas') < m.index('PySide6')"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_window_full_flow(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from main import MainWindow
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        with patch.object(Path, "home", return_value=self.folder):
            window = MainWindow()
        for key, filename in [("ctes", "puntos_ctes.xlsx"), ("resis", "puntos_resistencia.xlsx"),
                              ("pedidos", "reporte_pedidos.xlsx"), ("porcliente", "porcliente.xlsx")]:
            with patch.object(window, "choose_excel", return_value=str(self.folder / filename)):
                if key in {"ctes", "resis"}:
                    window.load_puntos(key)
                elif key == "pedidos":
                    window.load_pedidos()
                else:
                    window.load_porcliente()
        self.assertTrue(window.save_button.isEnabled())
        with patch.object(QMessageBox, "information"):
            window.save_load()
        self.assertIsNotNone(window.review_window)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), patch.object(QMessageBox, "information"):
            window.review_window.confirm_review()
            window.review_window.process_presale()
        self.assertIsNotNone(window.review_window.dashboard_window)
        app.processEvents()
        window.review_window.dashboard_window.close()
        window.review_window.close()
        window.close()

    def test_gui_confirmation_sort_and_dashboard(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from app.review_window import ReviewWindow
        from app.dashboard_window import DashboardWindow, NumericItem
        from PySide6.QtWidgets import QApplication, QTableWidget, QMessageBox
        from PySide6.QtCore import Qt
        app = QApplication.instance() or QApplication([])
        window = ReviewWindow(self.session)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), patch.object(QMessageBox, "information"):
            window.confirm_review()
        self.assertTrue(window.process_button.isEnabled())
        data = process_presale(self.session)
        dashboard = DashboardWindow(data)
        dashboard.show()
        app.processEvents()
        table = QTableWidget(2, 1)
        table.setItem(0, 0, NumericItem(100, "$100"))
        table.setItem(1, 0, NumericItem(20, "$20"))
        table.sortItems(0, Qt.AscendingOrder)
        self.assertEqual(table.item(0, 0).value, 20)
        window.handle_change()
        self.assertFalse(window.process_button.isEnabled())
        self.assertTrue(window.confirm_button.isEnabled())
        dashboard.close()
        window.close()

    def test_alerts_collapsed_expand_and_collapse(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from app.alerts_widget import AlertsWidget
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        app = QApplication.instance() or QApplication([])
        panel = AlertsWidget(["Primera alerta", "Segunda alerta"])
        panel.show()
        app.processEvents()
        self.assertFalse(panel.details.isVisible())
        self.assertIn("(2)", panel.toggle.text())
        panel.toggle.click()
        self.assertTrue(panel.details.isVisible())
        self.assertEqual(panel.toggle.arrowType(), Qt.DownArrow)
        self.assertEqual(panel.details.toPlainText(), "Primera alerta\n\nSegunda alerta")
        panel.toggle.click()
        self.assertFalse(panel.details.isVisible())
        panel.close()


if __name__ == "__main__":
    unittest.main()
