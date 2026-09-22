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
from app.week_calendar import BRANCHES, as_date, delivery_for_presale
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
            return f"puntos:semanal:{self.branch}"
        if self.kind == "liquidacion":
            return f"liquidacion:{self.hash}"
        if self.kind == "pedidos":
            return f"pedidos:{self.hash}"
        return self.kind

    def validate(self, week):
        if self.error:
            raise ValueError(self.error)
        if self.kind not in {"puntos", "pedidos", "porcliente", "liquidacion"}:
            raise ValueError("Tipo de archivo no reconocido")
        start, end = as_date(self.coverage_start), as_date(self.coverage_end)
        if not week["start_date"] <= start.isoformat() <= end.isoformat() <= week["end_date"]:
            raise ValueError("Las fechas deben estar dentro de la semana seleccionada")
        if self.kind == "puntos":
            if self.branch not in BRANCHES:
                raise ValueError("Elegí Corrientes o Resistencia para cada archivo de Puntos")
            for value in self.metadata.get("presale_dates", [self.detected_start]):
                day = as_date(value)
                delivery = delivery_for_presale(day).isoformat()
                if day.weekday() == 6 or not week["start_date"] <= delivery <= week["end_date"]:
                    raise ValueError("SIGO debe contener preventa del sábado anterior al viernes de esta semana")
        else:
            if not self.metadata.get("coverage_confirmed"):
                raise ValueError("Falta indicar la semana del reporte")
        if self.kind == "liquidacion" and start != end:
            raise ValueError("Asociá la liquidación a una sola fecha")


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
        result = validate_puntos(path, "por confirmar", allow_multiple=True)
        df = load_points_file(path)
        dates = parse_date_series(df.loc[df["idcliente"].notna(), "dia"])
        candidate.metadata["presale_dates"] = sorted({d.isoformat() for d in dates.dropna()})
        candidate.branch = detect_branch(df)
        seller_column = "d_perso"
    elif candidate.kind == "pedidos":
        result = validate_pedidos(path)
        df = load_orders_file(path)
        df = df[df["NÚMERO PEDIDO"].notna()]
        dates = parse_date_series(df["FECHA ENTREGA"])
        seller_column = "VENDEDOR DEL PEDIDO"
        candidate.metadata["invalid_dates"] = int(dates.isna().sum())
    else:
        result = validate_porcliente(path)
        df = load_porcliente_file(path)
        dates = parse_date_series(df["Descripción Período"])
        seller_column = "Descripción Vendedor"
        candidate.metadata["date_mode"] = "delivery"
    if not result.valid:
        candidate.error = result.message
    valid = dates.dropna()
    if not valid.empty:
        candidate.detected_start = min(valid).isoformat()
        candidate.detected_end = max(valid).isoformat()
        candidate.coverage_start = candidate.detected_start
        candidate.coverage_end = candidate.detected_end
        if candidate.kind == "puntos":
            candidate.coverage_start = delivery_for_presale(min(valid)).isoformat()
            candidate.coverage_end = delivery_for_presale(max(valid)).isoformat()
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
