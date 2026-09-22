"""Reglas semanales con Excel sintéticos; nunca se toca el historial real."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from app.week_calendar import week_bounds, week_id, calendar_weeks, BRANCHES
from app.week_imports import inspect_upload, inspect_batch, UploadCandidate, detect_branch
from app.week_store import WeekStore, file_hash
from app.week_service import WeekService
from test_presale import physical, article, point

MON = date(2026, 9, 21)
SUN = date(2026, 9, 27)


class WeekTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = WeekStore(self.root / "private")
        self.key = self.store.ensure_week(MON)["id"]
        self.service = WeekService(self.store, today=date(2026, 9, 30))
        self.serial = 0

    def excel(self, rows):
        self.serial += 1
        path = self.root / f"archivo_aleatorio_{self.serial}.xlsx"
        pd.DataFrame(rows).to_excel(path, index=False)
        return path

    def points(self, day=MON, branch="corrientes", seller="A", client=1, visited=1):
        row = point(client, seller, visited)
        row["dia"] = day.strftime("%d/%m/%Y")
        candidate = inspect_upload(self.excel([row]))
        candidate.branch = branch
        return candidate

    def report(self, rows, start=MON, end=SUN, mode="commercial"):
        candidate = inspect_upload(self.excel(rows))
        candidate.coverage_start = start.isoformat()
        candidate.coverage_end = end.isoformat()
        candidate.metadata.update(coverage_confirmed=True, date_mode=mode)
        return candidate

    def order(self, number=1, day=MON, seller="A", client=1, total=100):
        return physical(number, seller, client, total, day.strftime("%d/%m/%Y"))

    def line(self, day=MON, seller="A", client=1, code=10, amount=100):
        row = article(client, seller, code, amount)
        row["Descripción Período"] = day.strftime("%d/%m/%Y")
        return row

    def upload(self, *candidates):
        return self.store.commit_uploads(self.key, candidates, self.store.week(self.key)["revision"])

    def base_data(self):
        self.upload(self.points(), self.points(branch="resistencia", seller="B", client=2),
                    self.report([self.order()]), self.report([self.line()]))

    def ready_to_close(self):
        self.base_data()
        for offset in range(1, 6):
            self.store.set_worked(self.key, MON + timedelta(days=offset), BRANCHES, False, "Feriado ficticio")
        session, _, _, rev = self.service.build_session(self.key)
        self.service.confirm_review(self.key, session, rev)
        for day in [MON, SUN]:
            self.store.confirm_liquidations(self.key, day, "Sin repartos pendientes")

    def test_01_calendar_monday_sunday_and_year_boundary(self):
        self.assertEqual(week_bounds(date(2026, 9, 23)), (MON, SUN))
        self.assertIn(MON, calendar_weeks(MON))
        self.assertEqual(week_id(date(2027, 1, 1)), "2026-W53")

    def test_02_sunday_belongs_ending_week(self):
        self.assertEqual(week_id(SUN), self.key)

    def test_03_monday_starts_new_week(self):
        self.assertNotEqual(week_id(SUN + timedelta(days=1)), self.key)

    def test_04_multiple_points_batch(self):
        candidates = [self.points(), self.points(branch="resistencia", seller="B", client=2),
                      self.points(day=MON + timedelta(days=1), client=3)]
        self.assertEqual(len(inspect_batch([c.path for c in candidates])), 3)
        self.assertEqual(len(self.upload(*candidates)), 3)
        self.assertEqual(len(self.store.uploads(self.key, active=True)), 3)

    def test_05_branch_requires_selection_even_with_arbitrary_filename(self):
        c = self.points()
        c.branch = ""
        with self.assertRaisesRegex(ValueError, "Elegí"):
            self.upload(c)
        self.assertEqual(detect_branch(pd.DataFrame({"Sucursal": ["Corrientes"]})), "corrientes")

    def test_06_date_detected_from_content(self):
        c = self.points(day=MON + timedelta(days=1))
        self.assertEqual(c.detected_start, "2026-09-22")

    def test_07_hash_duplicate_under_another_name(self):
        c = self.points()
        self.upload(c)
        copy = self.root / "otro_nombre.xlsx"
        shutil.copy2(c.path, copy)
        result = self.upload(inspect_upload(copy))
        self.assertEqual(result[0]["status"], "DUPLICADO")
        self.assertEqual(len(self.store.uploads(self.key)), 1)
        self.assertTrue(self.store.query("SELECT * FROM audit_events WHERE action='duplicado_rechazado'"))

    def test_08_same_day_branch_new_version(self):
        first = self.points()
        self.upload(first)
        self.upload(self.points(visited=0))
        versions = self.store.uploads(self.key)
        self.assertEqual([v["version"] for v in versions], [1, 2])
        self.assertEqual(file_hash(versions[0]["file_path"]), first.hash)

    def test_09_only_latest_confirmed_active(self):
        self.upload(self.points())
        second = self.points(visited=0)
        # La inspección por sí sola no cambia la activa.
        self.assertEqual(self.store.uploads(self.key, True)[0]["version"], 1)
        self.upload(second)
        self.assertEqual(self.store.uploads(self.key, True)[0]["version"], 2)

    def test_10_cumulative_orders_replace_not_sum(self):
        self.upload(self.report([self.order()], end=MON))
        self.upload(self.report([self.order(), self.order(2, MON + timedelta(days=1), total=200)], end=MON + timedelta(days=1)))
        data = self.service.metrics(self.key)
        self.assertEqual(data["company"]["sale"], 300)
        self.assertEqual(data["company"]["buyers"], 1)
        self.assertEqual(data["company"]["logical_orders"], 2)

    def test_11_cumulative_articles_replace_not_sum(self):
        tue = MON + timedelta(days=1)
        self.upload(self.report([self.order(), self.order(2, tue)]))
        self.upload(self.report([self.line()], end=MON))
        self.upload(self.report([self.line(), self.line(tue)], end=tue))
        data = self.service.metrics(self.key)
        self.assertEqual(data["articles"][0]["sale"], 200)
        self.assertEqual(data["articles"][0]["clients"], 1)
        self.assertEqual(data["providers"][0]["clients"], 1)

    def test_12_no_work_both_branches(self):
        self.store.set_worked(self.key, MON, BRANCHES, False, "Feriado")
        day = self.service.progress(self.key)["days"][0]
        self.assertEqual(day["state"], "NO_TRABAJADA")
        self.assertEqual(day["missing"], [])

    def test_13_no_work_corrientes_only(self):
        self.store.set_worked(self.key, MON, ["corrientes"], False)
        day = self.service.progress(self.key)["days"][0]
        self.assertEqual(day["branches"]["corrientes"], "NO SE TRABAJÓ")
        self.assertIn("Puntos resistencia", day["missing"])

    def test_14_no_work_resistencia_only(self):
        self.store.set_worked(self.key, MON, ["resistencia"], False)
        self.assertIn("Puntos corrientes", self.service.progress(self.key)["days"][0]["missing"])

    def test_15_revert_no_work(self):
        self.store.set_worked(self.key, MON, BRANCHES, False)
        self.store.set_worked(self.key, MON, BRANCHES, True)
        self.assertEqual(self.service.progress(self.key)["days"][0]["state"], "PREVENTA_PENDIENTE")

    def test_16_future_not_missing(self):
        self.service.today = MON
        day = self.service.progress(self.key)["days"][1]
        self.assertEqual(day["state"], "FUTURA")
        self.assertEqual(day["missing"], [])
        self.service.today = MON - timedelta(days=1)
        self.upload(self.report([self.order()]))
        self.assertIsNone(self.service.metrics(self.key)["data_until"])

    def test_17_current_day_in_progress(self):
        self.service.today = MON
        day = self.service.progress(self.key)["days"][0]
        self.assertEqual(day["state"], "EN_CURSO")
        self.assertEqual(day["missing"], [])

    def test_18_sunday_no_sigo(self):
        day = self.service.progress(self.key)["days"][6]
        self.assertTrue(day["sunday"])
        self.assertFalse(any("Puntos" in m for m in day["missing"]))

    def test_19_sunday_sale_and_next_monday_excluded(self):
        self.upload(self.report([self.order(1, SUN), self.order(2, SUN + timedelta(days=1), total=999)]))
        data = self.service.metrics(self.key)
        self.assertEqual(data["company"]["sale"], 100)
        self.assertEqual(data["sunday"]["sale"], 100)

    def test_20_sunday_does_not_change_coverage_or_conversion(self):
        self.base_data()
        before = self.service.metrics(self.key)
        self.upload(self.report([self.order(), self.order(2, SUN, client=3)]))
        after = self.service.metrics(self.key)
        self.assertEqual(before["company"]["coverage_pct"], after["company"]["coverage_pct"])
        self.assertEqual(before["company"]["conversion_pct"], after["company"]["conversion_pct"])
        self.assertEqual(after["company"]["buyers"], 2)

    def test_21_average_excludes_nonworked_and_sunday(self):
        self.base_data()
        self.upload(self.report([self.order(), self.order(2, SUN, total=500)]))
        self.store.set_worked(self.key, MON + timedelta(days=1), BRANCHES, False)
        data = self.service.metrics(self.key)
        seller = next(s for s in data["sellers"] if s["seller"] == "A")
        self.assertEqual(seller["working_days"], 1)
        self.assertEqual(seller["average_daily_sale"], 100)
        self.assertEqual(seller["sale"], 600)

    def test_22_liquidation_count_without_expected_total(self):
        path = self.excel([{"Liquidación": "Reparto ficticio", "Importe": -20}])
        c = UploadCandidate(path, file_hash(path), "liquidacion", coverage_start=MON.isoformat(),
                            coverage_end=MON.isoformat(), metadata={"coverage_confirmed": True})
        self.upload(c)
        status = self.store.liquidations(self.key)[0]
        self.assertEqual(status["count_uploaded"], 1)
        self.assertFalse(status["confirmed_complete"])
        self.assertNotIn("expected_count", status)

    def test_23_confirm_liquidations(self):
        self.store.confirm_liquidations(self.key, MON, "Sin repartos")
        status = self.store.liquidations(self.key)[0]
        self.assertTrue(status["confirmed_complete"])
        self.assertIsNotNone(status["confirmed_at"])
        self.assertEqual(status["count_at_confirmation"], 0)

    def test_24_closed_week_blocks_mutations(self):
        self.ready_to_close()
        self.service.close(self.key)
        for operation in [lambda: self.store.set_worked(self.key, MON, BRANCHES, False),
                          lambda: self.upload(self.points(visited=0)),
                          lambda: self.store.confirm_liquidations(self.key, MON, "Nota")]:
            with self.assertRaisesRegex(ValueError, "cerrada"):
                operation()

    def test_25_reopen_allows_edits(self):
        self.ready_to_close()
        self.service.close(self.key)
        self.store.reopen(self.key, "Corrección administrativa")
        self.upload(self.points(visited=0))
        self.assertEqual(self.store.week(self.key)["status"], "REABIERTA")

    def test_26_original_snapshot_preserved_after_reclose(self):
        self.ready_to_close()
        path = self.service.close(self.key)
        original = path.read_bytes()
        self.store.reopen(self.key, "Recalcular")
        self.upload(self.report([self.order(total=200)]))
        session, _, _, rev = self.service.build_session(self.key)
        self.service.confirm_review(self.key, session, rev)
        self.store.confirm_liquidations(self.key, MON, "Confirmado")
        self.store.confirm_liquidations(self.key, SUN, "Sin reparto")
        second = self.service.close(self.key)
        self.assertNotEqual(path, second)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.service.metrics(self.key)["company"]["sale"], 200)

    def test_27_partial_data_until_available(self):
        self.service.today = MON + timedelta(days=2)
        self.upload(self.report([self.order()], end=MON))
        data = self.service.metrics(self.key)
        self.assertEqual(data["data_until"], MON.isoformat())
        self.assertFalse(data["commercial_complete"])
        self.assertEqual(data["company"]["sale"], 100)

    def test_28_missing_explanation(self):
        self.service.today = MON + timedelta(days=2)
        text = self.service.missing_explanation(self.key)
        self.assertIn("La jornada aún no terminó", text)
        self.assertIn("Domingo no requiere SIGO", text)
        self.assertIn("Falta cargar: Puntos corrientes", text)

    def test_29_db_outside_repository(self):
        self.assertEqual(self.store.db_path.parent, self.root / "private")
        with self.assertRaises(ValueError):
            WeekStore(Path(__file__).resolve().parents[1] / "datos")

    def test_30_basic_weekly_ui(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication, QFileDialog
        from app.week_window import WeeksWindow, WeekControlWindow, UploadDialog
        app = QApplication.instance() or QApplication([])
        with patch.object(QFileDialog, "getOpenFileNames") as chooser:
            window = WeeksWindow(self.service)
            chooser.assert_not_called()
        window.show()
        control = WeekControlWindow(self.service, self.key)
        control.show()
        self.assertEqual(control.tabs.count(), 8)
        c = self.points()
        preview = UploadDialog(self.service, self.key, [c.path])
        self.assertEqual(preview.candidates[0].kind, "puntos")
        self.assertEqual(preview.controls[0][1].currentData(), "")
        self.assertEqual(len(self.store.uploads(self.key)), 0)
        app.processEvents()
        preview.close()
        control.close()
        window.close()

    def test_versions_with_shorter_range_stay_historical(self):
        self.upload(self.report([self.order()], end=SUN))
        self.upload(self.report([self.order(total=200)], end=MON))
        self.assertEqual(self.service.metrics(self.key)["company"]["sale"], 100)
        self.assertFalse(self.store.uploads(self.key)[-1]["active"])

    def test_reassignment_survives_replacement_and_requires_confirmation(self):
        self.base_data()
        session, _, _, revision = self.service.build_session(self.key)
        session.orders[0].assigned_seller = "B"
        self.service.confirm_review(self.key, session, revision)
        self.upload(self.report([self.order(total=200)]))
        data = self.service.metrics(self.key)
        self.assertEqual(next(s for s in data["sellers"] if s["seller"] == "B")["sale"], 200)
        self.assertTrue(any("confirmada" in warning for warning in data["warnings"]))

    def test_delivery_period_cross_week_maps_to_sunday(self):
        row = self.order(1, SUN)
        row["FECHA ENTREGA"] = "28/09/2026"
        self.upload(self.report([row]), self.report([self.line(SUN + timedelta(days=1))], mode="delivery"))
        self.assertEqual(self.service.metrics(self.key)["articles"][0]["sale"], 100)
        monday = self.order(2, SUN + timedelta(days=1))
        monday["FECHA ENTREGA"] = "28/09/2026"
        self.upload(self.report([row, monday]))
        # El detalle por entrega no permite separar dos semanas del mismo cliente.
        data = self.service.metrics(self.key)
        self.assertEqual(data["company"]["sale"], 100)
        self.assertEqual(data["articles"], [])
        self.assertTrue(any("fuera del rango" in w for w in data["warnings"]))

    def test_ambiguous_day_articles_not_duplicated(self):
        tue = MON + timedelta(days=1)
        self.upload(self.report([self.order(), self.order(2, tue)]),
                    self.report([self.line(amount=200)], mode="aggregate"))
        self.assertEqual(self.service.metrics(self.key)["articles"][0]["sale"], 200)
        session, _, _, revision = self.service.build_session(self.key)
        session.sellers.append("B")
        session.orders[0].assigned_seller = "B"
        self.service.confirm_review(self.key, session, revision)
        self.assertEqual(self.service.metrics(self.key)["articles"], [])

    def test_duplicate_in_same_batch_and_stale_preview(self):
        a = self.points()
        self.assertEqual(self.upload(a, a)[1]["status"], "DUPLICADO")
        with self.assertRaisesRegex(ValueError, "cambió"):
            self.store.commit_uploads(self.key, [self.points(visited=0)], 0)

    def test_legacy_index_does_not_modify_or_sum_loads(self):
        for version in [1, 2]:
            folder = self.store.root / "HISTORIAL" / MON.isoformat() / f"carga_{version:02d}"
            folder.mkdir(parents=True)
            (folder / "revision_preventa.json").write_text('{"legacy":true}', encoding="utf-8")
        self.store.scan_legacy()
        self.store.scan_legacy()
        self.assertEqual(len(self.store.query("SELECT * FROM legacy_loads")), 2)
        self.assertEqual(self.service.metrics(self.key)["company"]["sale"], 0)
        self.assertEqual((folder / "revision_preventa.json").read_text(), '{"legacy":true}')

    def test_cannot_close_before_week_end_or_without_liquidations(self):
        self.ready_to_close()
        self.service.today = MON
        with self.assertRaises(ValueError):
            self.service.close(self.key)
        self.service.today = date(2026, 9, 30)
        self.upload(self.points(visited=0))
        with self.assertRaises(ValueError):
            self.service.close(self.key)

    def test_untouched_nonworked_activity_does_not_lower_coverage(self):
        self.base_data()
        self.store.set_worked(self.key, MON, ["resistencia"], False)
        data = self.service.metrics(self.key)
        self.assertEqual(data["company"]["assigned_clients"], 1)
        self.assertEqual(data["company"]["coverage_pct"], 100)

    def test_active_file_tampering_detected_even_with_cache(self):
        self.base_data()
        self.service.metrics(self.key)
        path = Path(self.store.uploads(self.key, active=True)[0]["file_path"])
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "modificado"):
            self.service.metrics(self.key)

    def test_annulled_excluded_and_reassigned_logical_orders(self):
        anulled = self.order(3, total=999)
        anulled["ANULADO"] = "SI"
        self.upload(self.points(), self.points(branch="resistencia", seller="B", client=2),
                    self.report([self.order(), self.order(2, seller="B"), anulled, self.order(4, seller="HUGO")]),
                    self.report([self.line(), self.line(seller="B")]))
        session, _, _, revision = self.service.build_session(self.key)
        next(o for o in session.orders if o.original_seller == "A").assigned_seller = "B"
        self.service.confirm_review(self.key, session, revision)
        data = self.service.metrics(self.key)
        self.assertEqual(data["company"]["sale"], 200)
        self.assertEqual(data["company"]["logical_orders"], 1)
        self.assertEqual(data["articles"][0]["sale"], 200)
        self.assertEqual(data["articles"][0]["clients"], 1)
        a = next(s for s in data["sellers"] if s["seller"] == "A")
        self.assertEqual(a["visited_clients"], 1)
        self.assertEqual(a["sale"], 0)

    def test_activity_outside_report_range_not_counted_as_zero_sale(self):
        self.base_data()
        self.upload(self.report([self.order(total=110)], end=MON))
        self.store.activate(self.key, self.store.uploads(self.key)[-1]["id"])
        self.upload(self.points(day=MON + timedelta(days=1), client=3))
        data = self.service.metrics(self.key)
        self.assertEqual(data["company"]["assigned_clients"], 2)
        self.assertEqual(data["company"]["conversion_pct"], 50)

    def test_sqlite_state_and_closed_read_only_survive_restart(self):
        self.ready_to_close()
        self.service.close(self.key)
        reopened_app = WeekService(WeekStore(self.store.root), today=self.service.today)
        self.assertEqual(reopened_app.metrics(self.key)["status"], "CERRADA")
        self.assertEqual(reopened_app.metrics(self.key)["company"]["sale"], 100)

    def test_closed_export_cannot_replace_source_history(self):
        self.ready_to_close()
        source = self.service.close(self.key)
        with self.assertRaisesRegex(ValueError, "protegido"):
            self.service.export(self.key, source)
        destination = self.root / "export.json"
        self.service.export(self.key, destination)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["status"], "CERRADA")

    def test_upload_dialog_confirms_and_closed_ui_disables_editing(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
        from app.week_window import UploadDialog, WeekControlWindow
        app = QApplication.instance() or QApplication([])
        candidate = self.points()
        preview = UploadDialog(self.service, self.key, [candidate.path])
        preview.controls[0][1].setCurrentIndex(1)
        with patch.object(QMessageBox, "information"):
            preview.commit()
        self.assertEqual(preview.result(), QDialog.Accepted)
        self.assertEqual(len(self.store.uploads(self.key)), 1)
        self.ready_to_close()
        self.service.close(self.key)
        window = WeekControlWindow(self.service, self.key)
        self.assertFalse(window.upload_button.isEnabled())
        self.assertFalse(window.review_button.isEnabled())
        self.assertEqual(window.close_button.text(), "REABRIR SEMANA")
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
