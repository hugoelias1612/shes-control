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
            description='Producto',decision='RECHAZADA',impact=-40)
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

    def test_return_order_counts_use_unique_orders_and_partial_matched_amount(self):
        from app.returns import return_order_stats
        data = self.data()
        stats = return_order_stats(data)
        self.assertEqual((stats['orders'], stats['affected'], stats['percent']), (1, 1, 100))
        self.assertEqual((stats['partial'], stats['total']), (1, 0))
        data['returns'][0]['impact'] = -40
        data['returns'][0]['automatic_amount'] = 40
        data['returns'].append(dict(data['returns'][0], automatic_amount=60, impact=-60))
        stats = return_order_stats(data)
        self.assertEqual((stats['affected'], stats['total'], stats['lines']), (1, 1, 2))

    def test_summary_can_format_rows_before_enabling_sort(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication
        from app.week_window import table
        from app.dashboard_window import NumericItem
        from PySide6.QtCore import Qt
        app=QApplication.instance() or QApplication([])
        grid=table(['Estado','Importe'], [['Z',10],['A',20]], sortable=False)
        grid.setItem(0,1,NumericItem(10,'$10'))
        grid.setItem(1,1,NumericItem(20,'$20'))
        grid.setSortingEnabled(True);grid.sortItems(0,Qt.AscendingOrder)
        self.assertEqual((grid.item(0,0).text(),grid.item(0,1).value),('A',20))
        grid.close()

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
