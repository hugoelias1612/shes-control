from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass
class ValidationResult:
    valid: bool
    file_type: str
    path: Path
    message: str
    rows: int = 0
    sellers: list[str] = None
    preventa_date: Optional[date] = None
    report_date: Optional[date] = None
    warnings: list[str] = None

    def __post_init__(self):
        if self.sellers is None:
            self.sellers = []

        if self.warnings is None:
            self.warnings = []


def clean_text(value) -> str:
    if pd.isna(value):
        return ""

    return str(value).strip()


def unique_clean(values) -> list[str]:
    result = []

    for value in values:
        text = clean_text(value)

        if text and text.lower() != "nan":
            result.append(text)

    return sorted(set(result))


def parse_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(
        series,
        errors="coerce",
        dayfirst=True,
        format="mixed",
    ).dt.date


# ============================================================
# DETALLE PUNTOS DE VENTA
# ============================================================

PUNTOS_REQUIRED_COLUMNS = {
    "idcliente",
    "CodClienteEmpresa",
    "nomcli",
    "ruta",
    "dia",
    "c_vendedor",
    "d_perso",
    "visitado",
    "horaVenta",
}


def find_puntos_header(path: Path):
    """
    Los archivos de SIGO tienen varias filas informativas antes
    del encabezado real.

    Buscamos automáticamente la fila que contiene:
    idcliente / d_perso / horaVenta.
    """

    with pd.ExcelFile(path) as excel:

        for sheet_name in excel.sheet_names:
            raw = pd.read_excel(
                excel,
                sheet_name=sheet_name,
                header=None,
                nrows=30,
            )

            for index, row in raw.iterrows():
                values = {
                    clean_text(value)
                    for value in row.tolist()
                    if not pd.isna(value)
                }

                if {
                    "idcliente",
                    "d_perso",
                    "horaVenta",
                }.issubset(values):
                    return sheet_name, index

        raise ValueError(
            "No encontré el encabezado esperado de Detalle Puntos de Venta."
        )


def validate_puntos(path: str, region: str) -> ValidationResult:
    path = Path(path)

    try:
        sheet_name, header_row = find_puntos_header(path)

        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=header_row,
        )

        df.columns = [
            clean_text(column)
            for column in df.columns
        ]

        missing = PUNTOS_REQUIRED_COLUMNS - set(df.columns)

        if missing:
            return ValidationResult(
                valid=False,
                file_type=f"Puntos {region}",
                path=path,
                message=(
                    "Faltan columnas obligatorias: "
                    + ", ".join(sorted(missing))
                ),
            )

        # Eliminamos filas sin cliente real
        df = df[df["idcliente"].notna()].copy()

        if df.empty:
            return ValidationResult(
                valid=False,
                file_type=f"Puntos {region}",
                path=path,
                message="El archivo no contiene clientes.",
            )

        parsed_dates = parse_date_series(df["dia"])
        if parsed_dates.isna().any():
            raise ValueError("Hay clientes con fecha de preventa vacía o inválida")
        dates = parsed_dates.unique()

        if len(dates) == 0:
            return ValidationResult(
                valid=False,
                file_type=f"Puntos {region}",
                path=path,
                message="No pude detectar la fecha de preventa.",
            )

        if len(dates) > 1:
            return ValidationResult(
                valid=False,
                file_type=f"Puntos {region}",
                path=path,
                message=(
                    "El archivo contiene más de una fecha de preventa: "
                    + ", ".join(str(d) for d in dates)
                ),
            )

        preventa_date = dates[0]

        sellers = unique_clean(df["d_perso"])

        return ValidationResult(
            valid=True,
            file_type=f"Puntos {region}",
            path=path,
            rows=len(df),
            sellers=sellers,
            preventa_date=preventa_date,
            message="Archivo válido.",
        )

    except Exception as error:
        return ValidationResult(
            valid=False,
            file_type=f"Puntos {region}",
            path=path,
            message=str(error),
        )


# ============================================================
# REPORTE PEDIDOS
# ============================================================

PEDIDOS_REQUIRED_COLUMNS = {
    "NÚMERO PEDIDO",
    "VENDEDOR DEL PEDIDO",
    "CLIENTE",
    "FECHA ENTREGA",
    "TOTAL",
    "FECHA/HORA DE ALTA",
    "FECHA/HORA DE ÚLTIMA MODIFICACIÓN",
    "MODIFICADO",
    "FACTURADO",
    "ANULADO",
}


def find_pedidos_sheet(path: Path):
    with pd.ExcelFile(path) as excel:

        best_sheet = None
        best_columns = set()

        for sheet_name in excel.sheet_names:
            try:
                sample = pd.read_excel(
                    excel,
                    sheet_name=sheet_name,
                    nrows=3,
                )

                columns = {
                    clean_text(column)
                    for column in sample.columns
                }

                matched = PEDIDOS_REQUIRED_COLUMNS.intersection(columns)

                if len(matched) > len(best_columns):
                    best_sheet = sheet_name
                    best_columns = matched

            except Exception:
                continue

        if best_sheet is None:
            raise ValueError(
                "No encontré una hoja compatible con Reporte de Pedidos."
            )

        return best_sheet


def clean_pedido_seller(value: str) -> str:
    """
    Convierte:
    '229 - HURTADO NESTOR'
    en:
    'HURTADO NESTOR'
    """

    text = clean_text(value)

    if " - " in text:
        first, rest = text.split(" - ", 1)

        if first.strip().isdigit():
            return rest.strip()

    return text


def validate_pedidos(
    path: str,
    preventa_date: Optional[date] = None,
) -> ValidationResult:

    path = Path(path)

    try:
        sheet_name = find_pedidos_sheet(path)

        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
        )

        df.columns = [
            clean_text(column)
            for column in df.columns
        ]

        missing = PEDIDOS_REQUIRED_COLUMNS - set(df.columns)

        if missing:
            return ValidationResult(
                valid=False,
                file_type="Reporte Pedidos",
                path=path,
                message=(
                    "Faltan columnas obligatorias: "
                    + ", ".join(sorted(missing))
                ),
            )

        df = df[df["NÚMERO PEDIDO"].notna()].copy()

        if df.empty:
            return ValidationResult(
                valid=False,
                file_type="Reporte Pedidos",
                path=path,
                message="No encontré pedidos.",
            )

        sellers = unique_clean(
            df["VENDEDOR DEL PEDIDO"].apply(clean_pedido_seller)
        )

        alta_dates = parse_date_series(
            df["FECHA/HORA DE ALTA"]
        )

        warnings = []

        detected_date = None

        valid_alta_dates = alta_dates.dropna()

        if not valid_alta_dates.empty:
            detected_date = (
                valid_alta_dates
                .value_counts()
                .idxmax()
            )

        if preventa_date is not None:
            same_day = alta_dates == preventa_date
            count_same_day = int(same_day.sum())

            if count_same_day == 0:
                return ValidationResult(
                    valid=False,
                    file_type="Reporte Pedidos",
                    path=path,
                    message=(
                        "No encontré ningún pedido con fecha de alta "
                        f"{preventa_date.strftime('%d/%m/%Y')}."
                    ),
                )

            other_dates = (
                alta_dates[
                    alta_dates.notna()
                    & (alta_dates != preventa_date)
                ]
                .value_counts()
            )

            if not other_dates.empty:
                total_others = int(other_dates.sum())

                warnings.append(
                    f"Hay {total_others} pedidos con fecha de alta "
                    "distinta a la fecha de preventa. "
                    "Se conservarán crudos y se excluirán de esta preventa."
                )

        return ValidationResult(
            valid=True,
            file_type="Reporte Pedidos",
            path=path,
            rows=len(df),
            sellers=sellers,
            preventa_date=detected_date,
            message="Archivo válido.",
            warnings=warnings,
        )

    except Exception as error:
        return ValidationResult(
            valid=False,
            file_type="Reporte Pedidos",
            path=path,
            message=str(error),
        )


# ============================================================
# POR CLIENTE / ARTÍCULOS
# ============================================================

PORCLIENTE_REQUIRED_COLUMNS = {
    "Descripción Período",
    "Cod. Cliente",
    "Descripción",
    "Ruta",
    "Descripción Vendedor",
    "Código",
    "Descripción.2",
    "División",
    "Descripción.5",
    "Cantidades Totales",
    "Importes Netos",
    "Importes Finales",
}


def find_porcliente_sheet(path: Path):
    with pd.ExcelFile(path) as excel:

        best_sheet = None
        best_score = 0

        for sheet_name in excel.sheet_names:
            try:
                sample = pd.read_excel(
                    excel,
                    sheet_name=sheet_name,
                    nrows=3,
                )

                columns = {
                    clean_text(column)
                    for column in sample.columns
                }

                score = len(
                    PORCLIENTE_REQUIRED_COLUMNS.intersection(columns)
                )

                if score > best_score:
                    best_sheet = sheet_name
                    best_score = score

            except Exception:
                continue

        if best_sheet is None:
            raise ValueError(
                "No encontré una hoja compatible con PorCliente."
            )

        return best_sheet


def validate_porcliente(path: str) -> ValidationResult:
    path = Path(path)

    try:
        sheet_name = find_porcliente_sheet(path)

        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
        )

        df.columns = [
            clean_text(column)
            for column in df.columns
        ]

        missing = PORCLIENTE_REQUIRED_COLUMNS - set(df.columns)

        if missing:
            return ValidationResult(
                valid=False,
                file_type="PorCliente",
                path=path,
                message=(
                    "Faltan columnas obligatorias: "
                    + ", ".join(sorted(missing))
                ),
            )

        df = df[
            df["Cod. Cliente"].notna()
            & df["Código"].notna()
        ].copy()

        if df.empty:
            return ValidationResult(
                valid=False,
                file_type="PorCliente",
                path=path,
                message="No encontré movimientos de clientes/artículos.",
            )

        sellers = unique_clean(
            df["Descripción Vendedor"]
        )

        period_dates = parse_date_series(
            df["Descripción Período"]
        ).dropna()

        report_date = None

        if not period_dates.empty:
            report_date = (
                period_dates
                .value_counts()
                .idxmax()
            )

        return ValidationResult(
            valid=True,
            file_type="PorCliente",
            path=path,
            rows=len(df),
            sellers=sellers,
            report_date=report_date,
            message="Archivo válido.",
        )

    except Exception as error:
        return ValidationResult(
            valid=False,
            file_type="PorCliente",
            path=path,
            message=str(error),
        )
