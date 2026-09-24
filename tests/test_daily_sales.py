import os
import unittest
from app.daily_sales import daily_sales, DailySalesPanel

class DailySalesTests(unittest.TestCase):
    def data(self):
        order = dict(logical_id='2026-09-14__A__1',client_code='1',client_name='Cliente',
            assigned_seller='A',preventa_day='2026-09-14',fully_annulled=False,
            net_total=100,valid_total=121,order_numbers=['10','11'])
        returned = dict(matched=True,matched_sale_ref=order['logical_id'],automatic_amount=40,
            amount_net=-80,amount_final=-96.8,date='2026-09-21',client='1',article='7',
            description='Producto',decision='RECHAZADA')
        return dict(preventa_date='2026-09-14 – 2026-09-20',sellers=[dict(seller='A')],
            review=dict(orders=[order,dict(order,logical_id='cancelled',fully_annulled=True)]),
            returns=[returned,dict(returned,matched=False,matched_sale_ref='',decision='APROBADA')])

    def test_delivery_day_partial_return_and_logical_count(self):
        rows = daily_sales(self.data())
        self.assertEqual(len(rows),1)
        row = rows[('A','2026-09-14')]
        self.assertEqual((row['buyers'],row['logical_orders']), (1,1))
        self.assertEqual((row['gross_net'],row['return_net'],row['net']), (100,40,60))
        self.assertAlmostEqual(row['return_final'],48.4)
        self.assertAlmostEqual(row['final'],72.6)
        self.assertEqual(len(row['returns']),1)

    def test_lazy_panel_and_detail_need_no_service(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication,QPushButton,QTableWidget
        app=QApplication.instance() or QApplication([])
        panel=DailySalesPanel(self.data())
        self.assertFalse(panel.loaded)
        panel.show();app.processEvents()
        self.assertTrue(panel.loaded)
        self.assertEqual(len(panel.findChildren(QPushButton)),6)
        panel.open_detail(panel.rows[('A','2026-09-14')]);app.processEvents()
        grids=panel.dialogs[-1].findChildren(QTableWidget)
        self.assertEqual([g.rowCount() for g in grids],[1,1])
        panel.close()
