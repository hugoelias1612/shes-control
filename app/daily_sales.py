"""Daily delivery view built only from the current weekly snapshot."""
from datetime import date, timedelta


def daily_sales(data):
    sellers = {s['seller'] for s in data['sellers']}
    rows = {}
    def row(seller, day):
        return rows.setdefault((seller, day), dict(seller=seller, day=day, orders=[], returns=[],
            clients=set(), gross_net=0., gross_final=0., return_net=0., return_final=0.))
    references = {}
    for order in data.get('review', {}).get('orders', []):
        seller = order['assigned_seller']
        if order['fully_annulled'] or seller not in sellers:
            continue
        day = order['preventa_day']
        bucket = row(seller, day)
        bucket['orders'].append(order)
        bucket['clients'].add(order['client_code'])
        bucket['gross_final'] += order['valid_total']
        if order.get('net_total') is None:
            bucket['gross_net'] = None
        elif bucket['gross_net'] is not None:
            bucket['gross_net'] += order['net_total']
        references[order['logical_id']] = (seller, day)
    for movement in data.get('returns', []):
        # Only the part backed by a matched sale has an exact delivery day.
        destination = references.get(movement.get('matched_sale_ref'))
        amount = movement.get('automatic_amount', 0)
        if not movement.get('matched') or not destination or amount <= 0:
            continue
        bucket = row(*destination)
        total = abs(movement['amount_net'])
        final = abs(movement['amount_final']) * amount / total if total else 0
        bucket['return_net'] += amount
        bucket['return_final'] += final
        bucket['returns'].append(dict(movement, applied_net=amount, applied_final=final))
    for bucket in rows.values():
        bucket['logical_orders'] = len({(o['client_code'], o['assigned_seller'], o['preventa_day']) for o in bucket['orders']})
        bucket['buyers'] = len(bucket.pop('clients'))
        bucket['net'] = None if bucket['gross_net'] is None else bucket['gross_net'] - bucket['return_net']
        bucket['final'] = bucket['gross_final'] - bucket['return_final']
    return rows


def currency(value):
    if value is None:
        return 'No disponible'
    return '$' + f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QLineEdit, QDialog, QTabWidget)


class DailySalesPanel(QWidget):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.rows = None
        self.dialogs = []
        self.loaded = False
        self.layout_box = QVBoxLayout(self)

    def showEvent(self, event):
        super().showEvent(event)
        if self.loaded:
            return
        self.loaded = True
        self.rows = daily_sales(self.data)
        help_text = QLabel('Pedidos por fecha de entrega · Vendedor según Revisión. Ventas: importes de Pedidos. '
            'Se descuentan únicamente las partes de devoluciones conciliadas con una venta de ese día, incluso si se registraron después. '
            'Aprobaciones manuales sin venta identificada y excedentes sin respaldo no se atribuyen a un día. '
            'Esta vista puede diferir del resumen general basado en PorCliente.')
        help_text.setWordWrap(True)
        self.layout_box.addWidget(help_text)
        search = QLineEdit(); search.setPlaceholderText('Buscar vendedor…')
        self.layout_box.addWidget(search)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); layout = QVBoxLayout(content)
        self.seller_cards = []
        start = date.fromisoformat(self.data['preventa_date'][:10])
        for seller in sorted(s['seller'] for s in self.data['sellers']):
            card = QFrame(); card.setObjectName('dailySeller')
            card.setStyleSheet('QFrame#dailySeller {background:white; border:1px solid #e0c45a; border-radius:8px;}')
            box = QVBoxLayout(card)
            values = [v for (s, d), v in self.rows.items() if s == seller and date.fromisoformat(d).weekday() < 6]
            gross = sum(v['gross_final'] for v in values)
            returned = sum(v['return_final'] for v in values)
            gross_net = None if any(v['gross_net'] is None for v in values) else sum(v['gross_net'] for v in values)
            return_net = sum(v['return_net'] for v in values)
            net = None if gross_net is None else gross_net - return_net
            title = QLabel(f"{seller} · Lunes a sábado · {sum(v['logical_orders'] for v in values)} pedidos lógicos\n"
                           f"Antes de IVA: venta {currency(gross_net)} − devoluciones {currency(return_net)} = {currency(net)}\n"
                           f"Con IVA: venta {currency(gross)} − devoluciones {currency(returned)} = {currency(gross-returned)}")
            title.setWordWrap(True); box.addWidget(title)
            grid = QGridLayout()
            for i, name in enumerate(['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']):
                day = (start + timedelta(days=i)).isoformat()
                value = self.rows.get((seller, day))
                tile = QFrame(); tile.setStyleSheet('QFrame {background:#fffbea; border-radius:6px;}')
                tile_box = QVBoxLayout(tile)
                tile_box.addWidget(QLabel(f"{name} {day[8:10]}/{day[5:7]}"))
                if value:
                    text = (f"{value['buyers']} clientes · {value['logical_orders']} pedidos lógicos\n"
                        f"Antes de IVA: {currency(value['gross_net'])}\nCon IVA: {currency(value['gross_final'])}\n"
                        f"Devoluciones sin IVA: {currency(value['return_net'])}\nCon IVA: {currency(value['return_final'])}\n"
                        f"Resultado sin IVA: {currency(value['net'])}\nCon IVA: {currency(value['final'])}")
                else:
                    text = 'Sin pedidos de entrega cargados para este día.'
                label = QLabel(text); label.setWordWrap(True); tile_box.addWidget(label)
                button = QPushButton('Ver pedidos y devoluciones'); button.setEnabled(value is not None)
                button.clicked.connect(lambda checked=False, v=value: self.open_detail(v))
                tile_box.addWidget(button); grid.addWidget(tile, i // 3, i % 3)
            box.addLayout(grid)
            if any(s == seller and date.fromisoformat(d).weekday() == 6 for s, d in self.rows):
                button = QPushButton('Ver entregas del domingo (fuera del resumen de seis días)')
                day = (start + timedelta(days=6)).isoformat()
                button.clicked.connect(lambda checked=False, v=self.rows[(seller, day)]: self.open_detail(v))
                box.addWidget(button)
            layout.addWidget(card); self.seller_cards.append((seller, card))
        layout.addStretch(); scroll.setWidget(content); self.layout_box.addWidget(scroll)
        search.textChanged.connect(lambda text: [card.setVisible(text.casefold() in seller.casefold()) for seller, card in self.seller_cards])

    def open_detail(self, value):
        from app.week_window import table, filterable
        dialog = QDialog(self); dialog.setWindowTitle(f"{value['seller']} · Entrega {value['day']}")
        dialog.resize(1150, 650); layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"{value['buyers']} clientes · {value['logical_orders']} pedidos lógicos · "
            f"Devoluciones conciliadas antes de IVA: {currency(value['return_net'])}"))
        tabs = QTabWidget(); layout.addWidget(tabs)
        tabs.addTab(filterable(table(['Cliente', 'Nombre', 'Números CHESS', 'Entrega', 'Antes de IVA', 'Con IVA'],
            [[o['client_code'], o['client_name'], ', '.join(o['order_numbers']), o['preventa_day'],
              o.get('net_total') if o.get('net_total') is not None else 'No disponible', o['valid_total']] for o in value['orders']])), 'Pedidos')
        tabs.addTab(filterable(table(['Registro devolución', 'Entrega original', 'Cliente', 'Artículo', 'Descripción',
            'Antes de IVA aplicado', 'Con IVA aplicado', 'Referencia venta', 'Estado revisión'],
            [[r['date'], value['day'], r['client'], r['article'], r['description'], r['applied_net'],
              r['applied_final'], r['matched_sale_ref'], r['decision']] for r in value['returns']])), 'Devoluciones conciliadas')
        layout.addWidget(QLabel('Si figura RECHAZADA, el importe mostrado corresponde solo a la parte conciliada; el excedente rechazado no se descuenta.'))
        self.dialogs.append(dialog); dialog.show()
