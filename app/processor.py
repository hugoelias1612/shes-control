from __future__ import annotations

import json
from datetime import datetime
from collections import defaultdict
from pathlib import Path

import pandas as pd
from app.storage import write_json

from app.review_data import (
    ReviewSession,
    load_points_file,
    normalize_seller,
    clean_text,
    safe_float,
    is_yes,
    review_fingerprint,
    review_snapshot,
    parse_date_series,
)


# ============================================================
# UTILIDADES
# ============================================================

is_truthy = is_yes


def client_code(value) -> str:
    text = clean_text(value)

    if text.endswith(".0"):
        text = text[:-2]

    return text


def percentage(
    numerator: float,
    denominator: float,
) -> float:

    if not denominator:
        return 0.0

    return (
        numerator
        / denominator
        * 100
    )


# ============================================================
# ACTIVIDAD SIGO
# ============================================================

def build_activity_metrics(
    session: ReviewSession,
) -> dict:

    files = [
        session.folder / "puntos_ctes.xlsx",
        session.folder / "puntos_resistencia.xlsx",
    ]

    seller_clients = defaultdict(set)
    seller_visited = defaultdict(set)
    seller_sale_signal = defaultdict(set)

    for path in files:

        df = load_points_file(
            path
        )

        dates = parse_date_series(df["dia"])
        target = parse_date_series(pd.Series([session.preventa_date])).iloc[0]
        if dates.isna().any() or not dates.eq(target).all():
            raise ValueError("Fechas SIGO incompatibles con la preventa")

        for _, row in df.iterrows():

            seller = normalize_seller(
                row.get(
                    "d_perso",
                    "",
                )
            )

            code = client_code(
                row.get(
                    "CodClienteEmpresa",
                    "",
                )
            )

            if not seller or not code:
                continue

            seller_clients[
                seller
            ].add(
                code
            )

            if clean_text(row.get("horaVenta", "")):
                seller_sale_signal[seller].add(code)

            if is_truthy(
                row.get(
                    "visitado",
                    "",
                )
            ):
                seller_visited[
                    seller
                ].add(
                    code
                )

    result = {}

    for seller in session.sellers:

        assigned = seller_clients[
            seller
        ]

        visited = seller_visited[
            seller
        ]

        result[seller] = {
            "assigned_codes": sorted(assigned),
            "visited_codes": sorted(visited),
            "sale_signal_codes": sorted(seller_sale_signal[seller]),
            "assigned_clients": len(
                assigned
            ),

            "visited_clients": len(
                visited
            ),

            "not_visited_clients": max(
                len(assigned)
                - len(visited),
                0,
            ),
        }

    return result


# ============================================================
# MÉTRICAS DE ARTÍCULOS
# ============================================================

def aggregate_articles(
    orders,
    buyer_count: int,
    total_sale: float,
):

    articles = {}

    for order in orders:

        for article in order.articles:

            key = (
                article.code,
                article.provider,
            )

            if key not in articles:

                articles[key] = {
                    "code": article.code,
                    "name": article.name,
                    "provider": article.provider,

                    "quantity": 0.0,
                    "sale": 0.0,

                    "clients": set(),
                }

            item = articles[
                key
            ]

            item["quantity"] += (
                article.quantity
            )

            item["sale"] += (
                article.total
            )

            item["clients"].add(
                order.client_code
            )

    result = []

    for item in articles.values():

        client_count = len(
            item["clients"]
        )

        result.append(
            {
                "code": item[
                    "code"
                ],

                "name": item[
                    "name"
                ],

                "provider": item[
                    "provider"
                ],

                "quantity": round(
                    item["quantity"],
                    4,
                ),

                "sale": round(
                    item["sale"],
                    2,
                ),

                "clients": client_count,
                "client_codes": sorted(item["clients"]),

                "buyer_coverage_pct": round(
                    percentage(
                        client_count,
                        buyer_count,
                    ),
                    2,
                ),

                "sale_share_pct": round(
                    percentage(
                        item["sale"],
                        total_sale,
                    ),
                    2,
                ),
            }
        )

    return sorted(
        result,
        key=lambda item: item[
            "sale"
        ],
        reverse=True,
    )


# ============================================================
# MÉTRICAS DE PROVEEDORES
# ============================================================

def aggregate_providers(
    articles: list[dict],
    total_sale: float,
    buyer_count: int,
):

    providers = {}

    for article in articles:

        provider = (
            article["provider"]
            or "SIN PROVEEDOR"
        )

        if provider not in providers:

            providers[
                provider
            ] = {
                "provider": provider,
                "sale": 0.0,
                "quantity": 0.0,
                "articles": set(),
                "clients": set(),
            }

        item = providers[
            provider
        ]

        item["sale"] += (
            article["sale"]
        )

        item["quantity"] += (
            article["quantity"]
        )

        item["clients"].update(article["client_codes"])

        item["articles"].add(
            article["code"]
        )

    result = []

    for item in providers.values():

        result.append(
            {
                "provider": item[
                    "provider"
                ],

                "sale": round(
                    item["sale"],
                    2,
                ),

                "sale_share_pct": round(
                    percentage(
                        item["sale"],
                        total_sale,
                    ),
                    2,
                ),

                "quantity": round(
                    item["quantity"],
                    4,
                ),

                "article_count": len(
                    item["articles"]
                ),

                "clients": len(item["clients"]),

                "buyer_coverage_pct": round(
                    percentage(
                        len(item["clients"]),
                        buyer_count,
                    ),
                    2,
                ),
            }
        )

    return sorted(
        result,
        key=lambda item: item[
            "sale"
        ],
        reverse=True,
    )


# ============================================================
# PROCESAR PREVENTA
# ============================================================

def process_presale(
    session: ReviewSession,
) -> dict:

    fingerprint = review_fingerprint(session)
    if not session.confirmed_fingerprint or fingerprint != session.confirmed_fingerprint:
        raise ValueError("Debe confirmar las asignaciones actuales antes de procesar")
    saved = json.loads((session.folder / "revision_preventa.json").read_text(encoding="utf-8"))
    if saved.get("fingerprint") != fingerprint:
        raise ValueError("La revision guardada no coincide con la sesion")
    target = parse_date_series(pd.Series([session.preventa_date])).iloc[0]
    if pd.isna(target) or any(o.preventa_day != target.isoformat() for o in session.orders):
        raise ValueError("La sesion contiene pedidos fuera de la fecha de preventa")
    activity = (
        build_activity_metrics(
            session
        )
    )

    sellers_data = []

    # --------------------------------------------------------
    # Solo vendedores incluidos
    # --------------------------------------------------------

    included_sellers = [
        seller
        for seller in session.sellers
        if (
            seller
            not in session.excluded_sellers
        )
    ]

    # --------------------------------------------------------
    # Venta total empresa
    # --------------------------------------------------------

    company_orders = [
        order
        for order in session.orders
        if (
            not order.fully_annulled
            and order.assigned_seller
            in included_sellers
        )
    ]

    company_sale = sum(
        order.valid_total
        for order in company_orders
    )

    company_buyers = {
        order.client_code
        for order in company_orders
    }

    # --------------------------------------------------------
    # VENDEDORES
    # --------------------------------------------------------

    for seller in included_sellers:

        seller_orders = [
            order
            for order in session.orders
            if (
                order.assigned_seller
                == seller
                and not order.fully_annulled
            )
        ]

        valid_sale = sum(
            order.valid_total
            for order in seller_orders
        )

        buyers = {
            order.client_code
            for order in seller_orders
        }

        buyer_count = len(
            buyers
        )

        activity_data = (
            activity.get(
                seller,
                {
                    "assigned_clients": 0,
                    "visited_clients": 0,
                    "not_visited_clients": 0,
                },
            )
        )

        assigned = activity_data[
            "assigned_clients"
        ]

        visited = activity_data[
            "visited_clients"
        ]

        not_visited = activity_data[
            "not_visited_clients"
        ]

        coverage = percentage(
            visited,
            assigned,
        )

        portfolio_use = percentage(
            buyer_count,
            assigned,
        )

        conversion = percentage(
            buyer_count,
            visited,
        )

        average_ticket = (
            valid_sale
            / buyer_count
            if buyer_count
            else 0.0
        )

        articles = aggregate_articles(
            seller_orders,
            buyer_count,
            valid_sale,
        )

        providers = aggregate_providers(
            articles,
            valid_sale,
            buyer_count,
        )

        article_client_pairs = len({(o.client_code, a.code) for o in seller_orders for a in o.articles})

        average_mix = (
            article_client_pairs
            / buyer_count
            if buyer_count
            else 0.0
        )

        sellers_data.append(
            {
                "seller": seller,

                "sale": round(
                    valid_sale,
                    2,
                ),

                "company_share_pct": round(
                    percentage(
                        valid_sale,
                        company_sale,
                    ),
                    2,
                ),

                "assigned_clients": assigned,

                "visited_clients": visited,

                "not_visited_clients": (
                    not_visited
                ),

                "buyers": buyer_count,

                "coverage_pct": round(
                    coverage,
                    2,
                ),

                "portfolio_use_pct": round(
                    portfolio_use,
                    2,
                ),

                "conversion_pct": round(
                    conversion,
                    2,
                ),

                "average_ticket": round(
                    average_ticket,
                    2,
                ),

                "logical_orders": len({(o.client_code, o.assigned_seller, o.preventa_day) for o in seller_orders}),

                "average_article_mix": round(
                    average_mix,
                    2,
                ),

                "articles": articles,

                "providers": providers,
            }
        )

    sellers_data.sort(
        key=lambda seller: seller[
            "sale"
        ],
        reverse=True,
    )

    # --------------------------------------------------------
    # EMPRESA
    # --------------------------------------------------------

    assigned_codes = set().union(*(set(activity[s]["assigned_codes"]) for s in included_sellers))
    visited_codes = set().union(*(set(activity[s]["visited_codes"]) for s in included_sellers))
    company_assigned = len(assigned_codes)
    company_visited = len(visited_codes)
    company_not_visited = len(assigned_codes - visited_codes)

    company_buyer_count = len(
        company_buyers
    )

    company_ticket = (
        company_sale
        / company_buyer_count
        if company_buyer_count
        else 0.0
    )

    company_articles = (
        aggregate_articles(
            company_orders,
            company_buyer_count,
            company_sale,
        )
    )

    company_providers = (
        aggregate_providers(
            company_articles,
            company_sale,
            company_buyer_count,
        )
    )

    company_article_client_pairs = len({(o.client_code, a.code) for o in company_orders for a in o.articles})

    company_average_mix = (
        company_article_client_pairs
        / company_buyer_count
        if company_buyer_count
        else 0.0
    )

    warnings = list(session.warnings)
    for seller in included_sellers:
        signal = set(activity[seller]["sale_signal_codes"])
        original_clients = {o.client_code for o in session.orders if o.original_seller == seller}
        if signal - original_clients:
            warnings.append(f"{seller}: {len(signal - original_clients)} clientes con Hora Venta sin pedido conciliado. No se inventan importes ni compradores.")
    data = {
        "schema_version": 1,
        "processed_at": datetime.now().astimezone().isoformat(),
        "review_fingerprint": fingerprint,
        "review": review_snapshot(session),
        "warnings": warnings,
        "activity": activity,
        "article_source": "PorCliente de una jornada, sin anulados; periodo puede ser entrega",

        "preventa_date": (
            session.preventa_date
        ),

        "status": (
            "PREVENTA_PROCESADA"
        ),

        "final_numbers": False,

        "liquidations_required": True,

        "company": {
            "original_sale": round(sum(o.original_total for o in session.orders if o.assigned_seller in included_sellers), 2),
            "sale": round(
                company_sale,
                2,
            ),

            "included_sellers": len(
                included_sellers
            ),

            "excluded_sellers": len(
                session.excluded_sellers
            ),

            "assigned_clients": (
                company_assigned
            ),

            "visited_clients": (
                company_visited
            ),

            "not_visited_clients": (
                company_not_visited
            ),

            "buyers": (
                company_buyer_count
            ),

            "coverage_pct": round(
                percentage(
                    company_visited,
                    company_assigned,
                ),
                2,
            ),

            "portfolio_use_pct": round(
                percentage(
                    company_buyer_count,
                    company_assigned,
                ),
                2,
            ),

            "conversion_pct": round(
                percentage(
                    company_buyer_count,
                    company_visited,
                ),
                2,
            ),

            "average_ticket": round(
                company_ticket,
                2,
            ),

            "logical_orders": len({(o.client_code, o.assigned_seller, o.preventa_day) for o in company_orders}),

            "average_article_mix": round(
                company_average_mix,
                2,
            ),
        },

        "sellers": sellers_data,

        "articles": (
            company_articles
        ),

        "providers": (
            company_providers
        ),
    }

    destination = (
        session.folder
        / "preventa_procesada.json"
    )

    write_json(destination, data)

    return data