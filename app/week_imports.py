"""Inspección previa de archivos. Ninguna copia se realiza hasta confirmar el lote."""
from dataclasses import dataclass, field
from pathlib import Path
import re

import pandas as pd

from app.importers import (PEDIDOS_REQUIRED_COLUMNS,
                           PORCLIENTE_REQUIRED_COLUMNS, parse_date_series,
                           validate_puntos, validate_pedidos, validate_porcliente)
from app.review_data import (clean_text, normalize_text, normalize_seller,
                             load_points_file, load_orders_file, load_porcliente_file)
from app.week_calendar import BRANCHES, as_date
from app.week_store import file_hash


@dataclass
class UploadCandidate:
    path: Path
    hash: str
    kind: str
    detected_start: str = ""
    detected_end: str = ""
    coverage_start: str = ""
    coverage_end: str = ""
    branch: str = ""
    sellers: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: str = ""

    @property
    def logical_key(self):
        if self.kind == "puntos":
            return f"puntos:{self.coverage_start}:{self.branch}"
        if self.kind == "liquidacion":
            return f"liquidacion:{self.hash}"
        return self.kind

    def validate(self, week):
        if self.error:
            raise ValueError(self.error)
        if self.kind not in {"puntos", "pedidos", "porcliente", "liquidacion"}:
            raise ValueError("Tipo de archivo no reconocido")
        start, end = as_date(self.coverage_start), as_date(self.coverage_end)
        if not week["start_date"] <= start.isoformat() <= end.isoformat() <= week["end_date"]:
            raise ValueError("El rango comercial debe estar dentro de la semana seleccionada")
        if self.kind == "puntos":
            if self.branch not in BRANCHES:
                raise ValueError("Elegí Corrientes o Resistencia para cada archivo de Puntos")
            if start != end or start.weekday() == 6 or start.isoformat() != self.detected_start:
                raise ValueError("Puntos debe conservar su fecha detectada, de lunes a sábado")
        else:
            if not self.metadata.get("coverage_confirmed"):
                raise ValueError("Confirmá el rango comercial exportado, incluidos días sin movimientos")
        if self.kind == "porcliente" and self.metadata.get("date_mode") not in {"aggregate", "commercial", "delivery"}:
            raise ValueError("Indicá cómo interpretar las fechas de PorCliente")
        if self.kind == "liquidacion" and start != end:
            raise ValueError("Asociá la liquidación a una sola jornada comercial")


def detect_branch(dataframe):
    """Sugerencia basada exclusivamente en campos explícitos; el usuario siempre elige."""
    found = set()
    for column in dataframe.columns:
        if normalize_text(column) in {"SUCURSAL", "DESCRIPCION SUCURSAL", "ZONA"}:
            for value in dataframe[column].dropna():
                normalized = normalize_text(value)
                for branch in BRANCHES:
                    if re.search(rf"\b{branch.upper()}\b", normalized):
                        found.add(branch)
    return next(iter(found)) if len(found) == 1 else ""


def inspect_upload(path):
    path = Path(path).resolve()
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Solo se admiten Excel .xlsx")
    candidate = UploadCandidate(path, file_hash(path), "desconocido")
    # Inspección acotada a encabezados. Nombres de archivo no participan.
    with pd.ExcelFile(path) as excel:
        candidates = set()
        for sheet in excel.sheet_names:
            raw = pd.read_excel(excel, sheet_name=sheet, header=None, nrows=30)
            for _, row in raw.iterrows():
                values = {clean_text(v) for v in row}
                if {"idcliente", "d_perso", "horaVenta"} <= values:
                    candidates.add("puntos")
            columns = {clean_text(c) for c in pd.read_excel(excel, sheet_name=sheet, nrows=0).columns}
            if PEDIDOS_REQUIRED_COLUMNS <= columns:
                candidates.add("pedidos")
            if PORCLIENTE_REQUIRED_COLUMNS <= columns:
                candidates.add("porcliente")
    if len(candidates) != 1:
        candidate.error = "Estructura no reconocida o ambigua. Liquidaciones se adjuntan desde su pestaña."
        return candidate
    candidate.kind = candidates.pop()
    if candidate.kind == "puntos":
        result = validate_puntos(path, "por confirmar")
        df = load_points_file(path)
        dates = parse_date_series(df.loc[df["idcliente"].notna(), "dia"])
        candidate.branch = detect_branch(df)
        seller_column = "d_perso"
    elif candidate.kind == "pedidos":
        result = validate_pedidos(path)
        df = load_orders_file(path)
        df = df[df["NÚMERO PEDIDO"].notna()]
        dates = parse_date_series(df["FECHA/HORA DE ALTA"])
        seller_column = "VENDEDOR DEL PEDIDO"
        candidate.metadata["invalid_dates"] = int(dates.isna().sum())
    else:
        result = validate_porcliente(path)
        df = load_porcliente_file(path)
        dates = parse_date_series(df["Descripción Período"])
        seller_column = "Descripción Vendedor"
        candidate.metadata["date_mode"] = "aggregate"
    if not result.valid:
        candidate.error = result.message
    valid = dates.dropna()
    if not valid.empty:
        candidate.detected_start = min(valid).isoformat()
        candidate.detected_end = max(valid).isoformat()
        candidate.coverage_start = candidate.detected_start
        candidate.coverage_end = candidate.detected_end
    elif candidate.kind != "porcliente":
        candidate.error = "No se detectaron fechas válidas"
    candidate.sellers = sorted({normalize_seller(v) for v in df[seller_column] if clean_text(v)})
    candidate.metadata["sellers"] = candidate.sellers
    return candidate


def inspect_batch(paths):
    result = []
    for path in paths:
        try:
            result.append(inspect_upload(path))
        except Exception as error:
            result.append(UploadCandidate(Path(path), "", "desconocido", error=str(error)))
    return result
