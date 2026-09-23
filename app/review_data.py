from __future__ import annotations

import json
import hashlib
import math
import re
import unicodedata

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.importers import (
    parse_date_series,
    validate_puntos,
    validate_pedidos,
    validate_porcliente,
    find_pedidos_sheet,
    find_porcliente_sheet,
    find_puntos_header,
)
from app.storage import write_json


# ============================================================
# FUNCIONES GENERALES
# ============================================================

def clean_text(value) -> str:
    """Convierte cualquier valor en texto limpio."""

    if pd.isna(value):
        return ""

    return str(value).strip()


def normalize_text(value) -> str:
    """
    Normalización para comparar nombres.

    Ejemplo:
        'César Ruiz Díaz' -> 'CESAR RUIZ DIAZ'
    """

    text = clean_text(value).upper()

    text = unicodedata.normalize("NFD", text)

    text = "".join(
        character
        for character in text
        if unicodedata.category(character) != "Mn"
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_seller(value) -> str:
    """
    Chess puede traer:
        229 - HURTADO NESTOR

    SIGO puede traer:
        HURTADO NESTOR

    Acá eliminamos el código inicial.
    """

    text = clean_text(value)

    if " - " in text:
        first_part, rest = text.split(" - ", 1)

        if first_part.strip().isdigit():
            text = rest

    return normalize_text(text)


def is_yes(value) -> bool:
    """Reconoce SI / SÍ / YES / 1 como verdadero."""

    text = normalize_text(value)

    return text in {
        "SI",
        "YES",
        "1",
        "1.0",
        "TRUE",
    }


def safe_float(value) -> float:
    """Convierte un valor numérico sin romper la aplicación."""

    try:
        if pd.isna(value) or clean_text(value) == "":
            return 0.0

        text = clean_text(value).replace("$", "").replace(" ", "")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        number = float(text)
        if not math.isfinite(number):
            raise ValueError("Importe no finito")
        return number

    except (TypeError, ValueError) as error:
        raise ValueError(f"Importe inválido: {value}") from error


def parse_client(value) -> tuple[str, str]:
    """
    Convierte:

        17846 - FERNANDEZ DANIELA

    en:

        ("17846", "FERNANDEZ DANIELA")
    """

    text = clean_text(value)

    if " - " in text:
        code, name = text.split(" - ", 1)

        return (
            code.strip().removesuffix(".0"),
            name.strip(),
        )

    return (
        text.removesuffix(".0"),
        text,
    )


def client_sort_key(client_code: str):
    """
    Permite ordenar:
        65
        127
        204
        18047

    numéricamente.
    """

    try:
        return int(float(client_code))

    except (TypeError, ValueError):
        return 999999999


def format_date(value) -> str:
    if pd.isna(value):
        return ""

    parsed = pd.to_datetime(
        value,
        errors="coerce",
        dayfirst=True,
    )

    if pd.isna(parsed):
        return clean_text(value)

    return parsed.strftime("%d/%m/%Y")


def format_datetime(value) -> str:
    if pd.isna(value):
        return ""

    parsed = pd.to_datetime(
        value,
        errors="coerce",
        dayfirst=True,
    )

    if pd.isna(parsed):
        return clean_text(value)

    return parsed.strftime("%d/%m/%Y %H:%M")


# ============================================================
# MODELOS
# ============================================================

@dataclass
class ArticleLine:
    code: str
    name: str
    provider: str = ""

    quantity: float = 0.0
    bonification: float = 0.0
    total: float = 0.0
    net_total: float | None = None

@dataclass
class LogicalOrder:
    """
    Un pedido lógico representa:

        1 cliente
        + 1 vendedor
        + 1 día de preventa

    Puede contener varios números de pedido físicos de Chess.
    """

    logical_id: str

    client_code: str
    client_name: str

    original_seller: str
    assigned_seller: str

    order_numbers: list[str] = field(
        default_factory=list
    )

    original_total: float = 0.0
    valid_total: float = 0.0
    net_total: float | None = None

    alta_date: str = ""
    delivery_date: str = ""

    status: str = "PENDIENTE"
    modified: bool = False
    fully_annulled: bool = False
    preventa_day: str = ""

    articles: list[ArticleLine] = field(
        default_factory=list
    )


@dataclass
class ReviewSession:

    folder: Path

    sellers: list[str]

    orders: list[LogicalOrder]

    excluded_sellers: set[str] = field(
        default_factory=set
    )

    preventa_date: str = ""
    warnings: list[str] = field(default_factory=list)
    excluded_orders: list[dict] = field(default_factory=list)
    confirmed_fingerprint: str = ""

    def orders_originally_from(
        self,
        seller: str,
    ) -> list[LogicalOrder]:
        """
        Para la pantalla de revisión mantenemos el pedido
        visible dentro del vendedor ORIGINAL.

        Aunque sea reasignado, todavía podemos ver
        de dónde salió.
        """

        orders = [
            order
            for order in self.orders
            if order.original_seller == seller
        ]

        return sorted(
            orders,
            key=lambda order: client_sort_key(
                order.client_code
            ),
        )

    def original_presale(
        self,
        seller: str,
    ) -> float:

        return sum(
            order.original_total
            for order in self.orders
            if order.original_seller == seller
        )

    def current_valid_presale(
        self,
        seller: str,
    ) -> float:

        return sum(
            order.valid_total
            for order in self.orders
            if (
                order.assigned_seller == seller
                and not order.fully_annulled
            )
        )

    def current_order_count(
        self,
        seller: str,
    ) -> int:

        return len({
            (order.client_code, order.assigned_seller, order.preventa_day)
            for order in self.orders
            if (
                order.assigned_seller == seller
                and not order.fully_annulled
            )
        })

    def current_client_count(
        self,
        seller: str,
    ) -> int:

        return len({
            order.client_code
            for order in self.orders
            if (
                order.assigned_seller == seller
                and not order.fully_annulled
            )
        })

    def reassignment_count(self) -> int:

        return sum(
            1
            for order in self.orders
            if (
                order.assigned_seller
                != order.original_seller
            )
        )

    def company_valid_total(self) -> float:
        """
        Total actual de vendedores incluidos.

        Un vendedor excluido no suma nada.
        """

        return sum(
            order.valid_total
            for order in self.orders
            if (
                order.assigned_seller
                not in self.excluded_sellers
                and order.assigned_seller
                != "SIN ASIGNAR"
                and not order.fully_annulled
            )
        )


# ============================================================
# LECTURA DE ARCHIVOS
# ============================================================

def load_points_file(path: Path) -> pd.DataFrame:

    sheet_name, header_row = (
        find_puntos_header(path)
    )

    df = pd.read_excel(
        path,
        sheet_name=sheet_name,
        header=header_row,
    )

    df.columns = [clean_text(column) for column in df.columns]
    return df


def load_orders_file(path: Path) -> pd.DataFrame:

    sheet_name = find_pedidos_sheet(path)

    df = pd.read_excel(
        path,
        sheet_name=sheet_name,
    )
    df.columns = [clean_text(column) for column in df.columns]
    return df


def load_porcliente_file(path: Path) -> pd.DataFrame:

    sheet_name = find_porcliente_sheet(path)

    df = pd.read_excel(
        path,
        sheet_name=sheet_name,
    )
    df.columns = [clean_text(column) for column in df.columns]
    return df


# ============================================================
# VENDEDORES
# ============================================================

def detect_sellers(
    points_ctes: pd.DataFrame,
    points_resis: pd.DataFrame,
    orders_df: pd.DataFrame,
) -> list[str]:

    sellers = set()

    for dataframe in [
        points_ctes,
        points_resis,
    ]:
        if "d_perso" not in dataframe.columns:
            continue

        for value in dataframe["d_perso"]:
            seller = normalize_seller(value)

            if seller:
                sellers.add(seller)

    if "VENDEDOR DEL PEDIDO" in orders_df.columns:

        for value in orders_df[
            "VENDEDOR DEL PEDIDO"
        ]:
            seller = normalize_seller(value)

            if seller:
                sellers.add(seller)

    return sorted(sellers)


# ============================================================
# ARTÍCULOS
# ============================================================

def build_article_map(
    porcliente_df: pd.DataFrame,
) -> dict[tuple[str, str], list[ArticleLine]]:
    """
    El PorCliente no tiene N° pedido.

    Como decidimos consolidar todos los pedidos del mismo
    cliente/vendedor/día, nos alcanza con:

        cliente + vendedor

    También agrupamos líneas repetidas del mismo artículo.
    """

    grouped = {}

    for _, row in porcliente_df.iterrows():

        client_code = clean_text(
            row.get(
                "Cod. Cliente",
                "",
            )
        )

        if client_code.endswith(".0"):
            client_code = client_code[:-2]

        seller = normalize_seller(
            row.get(
                "Descripción Vendedor",
                "",
            )
        )

        article_code = clean_text(
            row.get(
                "Código",
                "",
            )
        )

        if article_code.endswith(".0"):
            article_code = article_code[:-2]

        article_name = clean_text(
            row.get(
                "Descripción.2",
                "",
            )
        )

        provider = clean_text(
            row.get(
        "Descripción.5",
        "",
            )
        )

        if not client_code:
            continue

        if not seller:
            continue

        if not article_code:
            continue

        key = (
            client_code,
            seller,
        )

        if key not in grouped:
            grouped[key] = {}

        article_key = (article_code, normalize_text(provider))
        if article_key not in grouped[key]:

            grouped[key][article_key] = (
                ArticleLine(
                    code=article_code,
                    name=article_name,
                    provider=normalize_text(provider),
                    net_total=0.0,
                )
            )

        article = grouped[key][article_key]
        net = row.get("Importes Netos")
        if not clean_text(net):
            article.net_total = None
        elif article.net_total is not None:
            article.net_total += safe_float(net)

        article.quantity += safe_float(
            row.get(
                "Cantidades Totales",
                0,
            )
        )

        article.bonification += safe_float(
            row.get(
                "Bonific",
                0,
            )
        )

        article.total += safe_float(
            row.get(
                "Importes Finales",
                0,
            )
        )

    result = {}

    for key, article_dictionary in grouped.items():

        result[key] = sorted(
            article_dictionary.values(),
            key=lambda article: article.code,
        )

    return result


# ============================================================
# PEDIDOS LÓGICOS
# ============================================================

def build_logical_orders(
    orders_df: pd.DataFrame,
    article_map: dict,
    preventa_date,
    date_column="FECHA/HORA DE ALTA",
) -> list[LogicalOrder]:

    target = parse_date_series(pd.Series([preventa_date])).iloc[0]
    if pd.isna(target):
        raise ValueError("Fecha de preventa inválida")
    groups = {}
    seen_numbers = set()

    for _, row in orders_df.iterrows():
        number = clean_text(row.get("NÚMERO PEDIDO")).removesuffix(".0")
        if not number:
            continue
        if number in seen_numbers:
            raise ValueError(f"Número de pedido repetido: {number}")
        seen_numbers.add(number)

        seller = normalize_seller(
            row.get(
                "VENDEDOR DEL PEDIDO",
                "",
            )
        )

        client_code, client_name = (
            parse_client(
                row.get(
                    "CLIENTE",
                    "",
                )
            )
        )

        alta_raw = row.get(
            date_column,
            "",
        )

        alta_parsed = pd.to_datetime(
            alta_raw,
            errors="coerce",
            dayfirst=True,
            format="mixed",
        )

        if pd.isna(alta_parsed) or alta_parsed.date() != target:
            continue

        if not seller or not client_code:
            raise ValueError(f"Pedido {number} sin cliente o vendedor")

        preventa_day = alta_parsed.strftime("%Y-%m-%d")

        # ----------------------------------------------------
        # REGLA COMERCIAL SHES
        #
        # Un cliente + vendedor + fecha
        # = un único pedido lógico.
        # ----------------------------------------------------

        key = (
            client_code,
            seller,
            preventa_day,
        )

        if key not in groups:

            logical_id = (
                f"{preventa_day}"
                f"__{seller}"
                f"__{client_code}"
            )

            groups[key] = {
                "logical_id": logical_id,
                "client_code": client_code,
                "client_name": client_name,
                "seller": seller,

                "order_numbers": [],

                "original_total": 0.0,
                "valid_total": 0.0,
                "net_total": 0.0,

                "alta_values": [],
                "delivery_values": [],

                "annulled_count": 0,
                "factured_count": 0,
                "retained_count": 0,

                "total_rows": 0,
                "modified": False,
                "states": set(),
            }

        group = groups[key]

        group["total_rows"] += 1

        order_number = clean_text(
            row.get(
                "NÚMERO PEDIDO",
                "",
            )
        )

        if order_number.endswith(".0"):
            order_number = order_number[:-2]

        if order_number:
            group["order_numbers"].append(
                order_number
            )

        total = safe_float(
            row.get(
                "TOTAL",
                0,
            )
        )

        # Preventa original:
        # TODO lo originalmente cargado.
        group["original_total"] += total

        annulled = is_yes(
            row.get(
                "ANULADO",
                "",
            )
        )

        factured = is_yes(
            row.get(
                "FACTURADO",
                "",
            )
        )

        retained = is_yes(
            row.get(
                "RETENIDO",
                "",
            )
        )

        modified = is_yes(
            row.get(
                "MODIFICADO",
                "",
            )
        )

        group["states"].add("ANULADO" if annulled else "RETENIDO" if retained else "FACTURADO" if factured else "PENDIENTE")
        if annulled:
            group["annulled_count"] += 1

        else:
            # Preventa válida:
            # todo lo NO anulado.
            group["valid_total"] += total
            base = [row.get("NETO GRAVADO"), row.get("NO GRAVADO")]
            if any(not clean_text(value) for value in base):
                group["net_total"] = None
            elif group["net_total"] is not None:
                group["net_total"] += sum(safe_float(value) for value in base)

        if factured:
            group["factured_count"] += 1

        if retained:
            group["retained_count"] += 1

        if modified:
            group["modified"] = True

        group["alta_values"].append(
            row.get(
                "FECHA/HORA DE ALTA",
                "",
            )
        )

        group["delivery_values"].append(
            row.get(
                "FECHA ENTREGA",
                "",
            )
        )

    logical_orders = []

    for key, group in groups.items():

        total_rows = group["total_rows"]

        fully_annulled = (
            group["annulled_count"]
            == total_rows
        )

        # ----------------------------------------------------
        # ESTADO
        # ----------------------------------------------------

        status = next(iter(group["states"])) if len(group["states"]) == 1 else "MIXTO"

        # ----------------------------------------------------
        # FECHAS
        # ----------------------------------------------------

        valid_alta_dates = [
            pd.to_datetime(
                value,
                errors="coerce",
                dayfirst=True,
            )
            for value in group["alta_values"]
        ]

        valid_alta_dates = [
            value
            for value in valid_alta_dates
            if not pd.isna(value)
        ]

        if valid_alta_dates:
            alta_date = min(
                valid_alta_dates
            ).strftime(
                "%d/%m/%Y %H:%M"
            )
        else:
            alta_date = ""

        delivery_dates = set()

        for value in group[
            "delivery_values"
        ]:

            formatted = format_date(
                value
            )

            if formatted:
                delivery_dates.add(
                    formatted
                )

        delivery_date = ", ".join(
            sorted(delivery_dates)
        )

        articles = article_map.get(
            (
                group["client_code"],
                group["seller"],
            ),
            [],
        )

        logical_orders.append(
            LogicalOrder(
                net_total=group["net_total"],
                logical_id=group[
                    "logical_id"
                ],

                client_code=group[
                    "client_code"
                ],

                client_name=group[
                    "client_name"
                ],

                original_seller=group[
                    "seller"
                ],

                assigned_seller=group[
                    "seller"
                ],

                order_numbers=sorted(
                    set(
                        group[
                            "order_numbers"
                        ]
                    )
                ),

                original_total=group[
                    "original_total"
                ],

                valid_total=group[
                    "valid_total"
                ],

                alta_date=alta_date,

                delivery_date=(
                    delivery_date
                ),

                status=status,
                preventa_day=key[2],

                modified=group[
                    "modified"
                ],

                fully_annulled=(
                    fully_annulled
                ),

                articles=articles,
            )
        )

    return sorted(
        logical_orders,
        key=lambda order: (
            order.original_seller,
            client_sort_key(
                order.client_code
            ),
        ),
    )


# ============================================================
# SESIÓN COMPLETA
# ============================================================

def build_review_session(
    load_folder: Path,
) -> ReviewSession:

    load_folder = Path(
        load_folder
    )

    points_ctes = load_points_file(
        load_folder
        / "puntos_ctes.xlsx"
    )

    points_resis = load_points_file(
        load_folder
        / "puntos_resistencia.xlsx"
    )

    orders_df = load_orders_file(
        load_folder
        / "reporte_pedidos.xlsx"
    )

    porcliente_df = load_porcliente_file(
        load_folder
        / "porcliente.xlsx"
    )

    sellers = detect_sellers(
        points_ctes,
        points_resis,
        orders_df,
    )
    sellers = sorted(set(sellers) | {
        normalize_seller(v) for v in porcliente_df["Descripción Vendedor"] if clean_text(v)
    })

    points_validations = [
        validate_puntos(load_folder / "puntos_ctes.xlsx", "Corrientes"),
        validate_puntos(load_folder / "puntos_resistencia.xlsx", "Resistencia"),
    ]
    for result in points_validations:
        if not result.valid:
            raise ValueError(result.message)
    for result in [validate_pedidos(load_folder / "reporte_pedidos.xlsx"),
                   validate_porcliente(load_folder / "porcliente.xlsx")]:
        if not result.valid:
            raise ValueError(result.message)
    day = points_validations[0].preventa_date
    if day != points_validations[1].preventa_date:
        raise ValueError("Las fechas de Corrientes y Resistencia no coinciden")

    article_map = build_article_map(
        porcliente_df
    )

    orders = build_logical_orders(
        orders_df,
        article_map,
        day,
    )

    dates = parse_date_series(orders_df["FECHA/HORA DE ALTA"])
    excluded_orders = [
        {"number": clean_text(row["NÚMERO PEDIDO"]),
         "alta": clean_text(row["FECHA/HORA DE ALTA"]),
         "reason": "Fecha de alta distinta o inválida"}
        for index, row in orders_df.iterrows()
        if clean_text(row["NÚMERO PEDIDO"]) and dates.loc[index] != day
    ]
    warnings = []
    if excluded_orders:
        warnings.append(f"{len(excluded_orders)} pedidos fuera de fecha o sin fecha válida; conservados crudos y excluidos de esta preventa.")
    matched = {(o.client_code, o.original_seller) for o in orders if not o.fully_annulled}
    unmatched = set(article_map) - matched
    if unmatched:
        warnings.append(f"{len(unmatched)} combinaciones cliente/vendedor de PorCliente sin pedido válido en esta fecha; no suman métricas.")
    for order in orders:
        if order.fully_annulled:
            order.articles = []
        elif abs(round(sum(a.total for a in order.articles) - order.valid_total, 2)) > 0.02:
            warnings.append(f"Diferencia entre PorCliente y pedidos: {order.logical_id}. Revisar artículos e importes.")

    # --------------------------------------------------------
    # HUGO = usuario interno
    # --------------------------------------------------------

    excluded = {
        seller
        for seller in sellers
        if seller == "HUGO" or seller.startswith("HUGO ")
    }

    # --------------------------------------------------------
    # FECHA PREVENTA
    # --------------------------------------------------------

    return ReviewSession(
        folder=load_folder,
        sellers=sellers,
        orders=orders,
        excluded_sellers=excluded,
        preventa_date=day.strftime("%d/%m/%Y"),
        warnings=warnings,
        excluded_orders=excluded_orders,
    )


# ============================================================
# GUARDAR REVISIÓN
# ============================================================

def review_snapshot(session):
    return {
        "schema_version": 1,
        "preventa_date": session.preventa_date,
        "sellers": session.sellers,
        "excluded_sellers": sorted(session.excluded_sellers),
        "warnings": session.warnings,
        "excluded_orders": session.excluded_orders,
        "orders": [asdict(o) for o in session.orders],
        "reassignments": [
            {"logical_id": o.logical_id, "client_code": o.client_code,
             "original_seller": o.original_seller, "assigned_seller": o.assigned_seller}
            for o in session.orders if o.original_seller != o.assigned_seller
        ],
    }


def review_fingerprint(session):
    payload = json.dumps(review_snapshot(session), ensure_ascii=False,
                         sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_review(session):
    if any(o.assigned_seller not in session.sellers for o in session.orders
           if not o.fully_annulled):
        raise ValueError("Hay pedidos válidos sin vendedor asignado")
    fingerprint = review_fingerprint(session)
    data = review_snapshot(session)
    data.update(confirmed_at=datetime.now().astimezone().isoformat(), fingerprint=fingerprint)
    destination = write_json(session.folder / "revision_preventa.json", data)
    session.confirmed_fingerprint = fingerprint
    return destination
