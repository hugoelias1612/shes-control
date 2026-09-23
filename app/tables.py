"""Comportamiento uniforme de tablas, sin columnas forzadas al ancho disponible."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget


def configure_table(table, sortable=True):
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setSectionsMovable(True)
    header.setMinimumSectionSize(60)
    header.setDefaultSectionSize(145)
    for col in range(table.columnCount()):
        title = table.horizontalHeaderItem(col)
        text = title.text() if title else ""
        width = max(110, min(320, header.fontMetrics().horizontalAdvance(text) + 36))
        for row in range(min(table.rowCount(), 60)):
            item = table.item(row, col)
            if item:
                width = max(width, min(320, header.fontMetrics().horizontalAdvance(item.text().split("\n")[0]) + 26))
        table.setColumnWidth(col, width)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSortingEnabled(sortable)


def table_key(table):
    return tuple(table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else ""
                 for c in range(table.columnCount()))


def capture_tables(parent):
    return {table_key(t): (t.horizontalHeader().saveState(),
            [t.item(i.row(), 0).text() for i in t.selectionModel().selectedRows() if t.item(i.row(), 0)],
            t.horizontalScrollBar().value(), t.verticalScrollBar().value())
            for t in parent.findChildren(QTableWidget)}


def restore_tables(parent, state):
    from PySide6.QtCore import QItemSelectionModel
    for t in parent.findChildren(QTableWidget):
        previous = state.get(table_key(t))
        if not previous:
            continue
        header, selected, horizontal, vertical = previous
        t.horizontalHeader().restoreState(header)
        if t.isSortingEnabled():
            t.sortItems(t.horizontalHeader().sortIndicatorSection(), t.horizontalHeader().sortIndicatorOrder())
        t.clearSelection()
        for row in range(t.rowCount()):
            if t.item(row, 0) and t.item(row, 0).text() in selected:
                t.selectionModel().select(t.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        t.horizontalScrollBar().setValue(horizontal)
        t.verticalScrollBar().setValue(vertical)
