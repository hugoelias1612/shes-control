"""Correctness of performance paths: cache isolation and responsive Qt work."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

import pandas as pd
from app.week_store import WeekStore


class PerformanceTests(unittest.TestCase):
    def test_persistent_cache_preserves_types_and_isolated_frames(self):
        with tempfile.TemporaryDirectory() as root:
            store = WeekStore(Path(root))
            frame = pd.DataFrame({"code": ["001", "002"], "amount": [12.3456789, -2.5],
                                  "date": pd.to_datetime(["2026-09-14", "2026-09-15"])})
            upload = dict(hash="first", type="pedidos", file_path="unused")
            loader = Mock(return_value=frame)
            first = store.parsed_upload(upload, loader)
            second = WeekStore(Path(root)).parsed_upload(upload, loader)
            # JSON table standardizes datetime resolution to ns; values must match.
            pd.testing.assert_frame_equal(first, second, check_dtype=False)
            second.loc[0, "amount"] = 99
            pd.testing.assert_frame_equal(frame, store.parsed_upload(upload, loader), check_dtype=False)
            self.assertEqual(loader.call_count, 1)
            store.parsed_upload(dict(upload, hash="changed"), loader)
            self.assertEqual(loader.call_count, 2)

    def test_worker_keeps_event_loop_alive_and_propagates_errors(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from app.background import run_data
        app = QApplication.instance() or QApplication([])
        main_thread = threading.get_ident()
        ticks = []
        timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
        def action():
            time.sleep(.08)
            return threading.get_ident()
        try:
            self.assertNotEqual(run_data(None, action), main_thread)
            self.assertTrue(ticks)
            with self.assertRaisesRegex(ValueError, "expected"):
                run_data(None, lambda: (_ for _ in ()).throw(ValueError("expected")))
        finally:
            timer.stop()
            app.processEvents()
