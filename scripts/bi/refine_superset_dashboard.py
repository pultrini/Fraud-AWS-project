"""Refina o dashboard local do Superset sem consultar a AWS.

O script altera apenas os metadados de visualizacao do Superset. Antes de
qualquer mudanca, ele cria uma copia de seguranca do banco SQLite.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path("dashboard/superset/superset_home/superset.db")


def sqlite_datetime() -> str:
    """Formato de data esperado pelo SQLAlchemy ao ler DATETIME do SQLite."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def sql_metric(label: str, expression: str) -> dict[str, Any]:
    """Cria uma metrica SQL com rotulo legivel no grafico."""
    return {
        "expressionType": "SQL",
        "sqlExpression": expression,
        "column": None,
        "aggregate": None,
        "datasourceWarning": False,
        "hasCustomLabel": True,
        "label": label,
        "optionName": f"metric_{label.lower().replace(' ', '_')}",
    }


def load_slice(connection: sqlite3.Connection, slice_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT params FROM slices WHERE id = ?", (slice_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Grafico {slice_id} nao encontrado no Superset.")
    return json.loads(row[0])


def save_slice(
    connection: sqlite3.Connection,
    slice_id: int,
    params: dict[str, Any],
    *,
    name: str | None = None,
    viz_type: str | None = None,
) -> None:
    assignments = ["params = ?", "query_context = NULL", "changed_on = ?"]
    values: list[Any] = [
        json.dumps(params, ensure_ascii=False, separators=(",", ":")),
        sqlite_datetime(),
    ]
    if name is not None:
        assignments.append("slice_name = ?")
        values.append(name)
    if viz_type is not None:
        assignments.append("viz_type = ?")
        values.append(viz_type)
    values.append(slice_id)
    connection.execute(
        f"UPDATE slices SET {', '.join(assignments)} WHERE id = ?", values
    )


def refine_charts(connection: sqlite3.Connection) -> None:
    # O valor na fonte ja esta em pontos percentuais. Dividir por 100 permite
    # usar o formatador percentual do Superset sem transformar 0,129% em 12,9%.
    params = load_slice(connection, 6)
    params["metric"] = sql_metric(
        "Taxa de fraude", "MAX(fraud_rate_percent) / 100.0"
    )
    params["y_axis_format"] = ",.3%"
    save_slice(connection, 6, params, name="Taxa de fraude")

    params = load_slice(connection, 9)
    params["metrics"] = [
        sql_metric("Taxa de fraude (%)", "MAX(fraud_rate_percent)")
    ]
    params["y_axis_format"] = ",.2f"
    params["y_axis_title"] = "Taxa de fraude (%)"
    params["show_value"] = True
    save_slice(connection, 9, params, name="Taxa de fraude por tipo (%)")

    # Uma taxa comunica melhor o desempenho da regra do que duas barras com
    # escalas muito diferentes (16 detectadas contra milhares nao detectadas).
    params = load_slice(connection, 10)
    params["metrics"] = [
        sql_metric(
            "Taxa de detecção (%)", "MAX(fraud_detection_rate_percent)"
        )
    ]
    params["y_axis_format"] = ",.2f"
    params["y_axis_title"] = "Taxa de detecção (%)"
    params["show_value"] = True
    params["stack"] = None
    save_slice(connection, 10, params, name="Taxa de detecção da regra por tipo")

    # Compara taxa diaria com sua propria media movel, mantendo a mesma unidade.
    params = load_slice(connection, 11)
    params["metrics"] = [
        sql_metric("Taxa diária (%)", "MAX(fraud_rate_percent)"),
        sql_metric(
            "Média móvel de 7 dias (%)",
            "MAX(rolling_7d_fraud_rate_percent)",
        ),
    ]
    params["y_axis_format"] = ",.3f"
    params["y_axis_title"] = "Taxa de fraude (%)"
    params["x_axis_sort"] = "simulation_day"
    params["x_axis_sort_asc"] = True
    save_slice(connection, 11, params, name="Taxa diária e média móvel de 7 dias")

    params = load_slice(connection, 12)
    params["metrics"] = [
        sql_metric(
            "Variação (p.p.)",
            "MAX(fraud_rate_change_percentage_points)",
        )
    ]
    params["y_axis_format"] = ",.2f"
    params["y_axis_title"] = "Variação em pontos percentuais"
    params["x_axis_sort"] = "simulation_day"
    params["x_axis_sort_asc"] = True
    save_slice(connection, 12, params, name="Variação diária da taxa (p.p.)")

    # Contagem e valor monetario nao devem dividir o mesmo eixo.
    params = load_slice(connection, 14)
    params["metrics"] = [
        sql_metric("Fraudes acumuladas", "MAX(cumulative_fraud_count)")
    ]
    params["logAxis"] = False
    params["y_axis_format"] = "SMART_NUMBER"
    params["y_axis_title"] = "Quantidade acumulada"
    params["x_axis_sort"] = "simulation_day"
    params["x_axis_sort_asc"] = True
    save_slice(connection, 14, params, name="Fraudes acumuladas")

    params = load_slice(connection, 17)
    params["y_axis_title"] = "Valor transacionado"
    params["y_axis_format"] = "SMART_NUMBER"
    params["show_value"] = True
    save_slice(connection, 17, params, name="Valor transacionado por nível de risco")

    # Mantem o grao de cliente, mas usa o nivel de risco como serie visual.
    params = load_slice(connection, 18)
    params["groupby"] = ["customer_risk_level"]
    params["metrics"] = [
        sql_metric(
            "Valor médio por cliente",
            "AVG(transaction_amount_total)",
        )
    ]
    params["x_axis_title"] = "Quantidade de transações"
    params["y_axis_title"] = "Valor médio transacionado por cliente"
    params["y_axis_format"] = "SMART_NUMBER"
    params["row_limit"] = 10_000
    params["show_legend"] = True
    params["markerEnabled"] = True
    params["markerSize"] = 10
    save_slice(
        connection,
        18,
        params,
        name="Volume transacionado versus frequência",
    )

    # Tabela comum: uma linha por cliente, ordenada pela prioridade de risco.
    params = load_slice(connection, 19)
    params.update(
        {
            "viz_type": "table",
            "all_columns": [
                "customer_risk_rank",
                "customer_id",
                "customer_risk_level",
                "customer_role",
                "transaction_count",
                "transaction_amount_total",
                "maximum_transaction_amount",
                "fraudulent_transaction_count",
                "fraudulent_transaction_amount",
                "high_value_anomaly_count",
            ],
            "metrics": [],
            "groupby": [],
            "order_by_cols": ['["customer_risk_rank", true]'],
            "row_limit": 100,
            "page_length": 20,
            "include_search": True,
            "table_filter": True,
            "server_pagination": False,
            "show_cell_bars": True,
            "align_pn": False,
            "color_pn": True,
        }
    )
    for obsolete_key in (
        "groupbyColumns",
        "groupbyRows",
        "metricsLayout",
        "aggregateFunction",
        "transposePivot",
        "combineMetric",
    ):
        params.pop(obsolete_key, None)
    save_slice(
        connection,
        19,
        params,
        name="Fila priorizada de investigação",
        viz_type="table",
    )

    params = load_slice(connection, 21)
    params["normalized"] = False
    params["show_percentage"] = False
    params["show_values"] = True
    params["sort_x_axis"] = "alpha_asc"
    params["xAxisLabelRotation"] = 0
    params["y_axis_format"] = "SMART_NUMBER"
    save_slice(connection, 21, params, name="Fraudes por dia e tipo")


def refine_dashboard(connection: sqlite3.Connection, dashboard_id: int) -> None:
    row = connection.execute(
        "SELECT position_json, json_metadata FROM dashboards WHERE id = ?",
        (dashboard_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Dashboard {dashboard_id} nao encontrado.")

    position = json.loads(row[0])
    metadata = json.loads(row[1] or "{}")

    position["HEADER_ID"]["meta"]["text"] = "Financial Risk & Fraud Analytics"

    markdown = position.get("MARKDOWN-KMFWzNI6qpyMCGgQONO2H")
    if markdown:
        markdown["meta"].update(
            {
                "code": (
                    "## Tendências e detecção de fraude\n"
                    "PaySim · 6,36 milhões de transações simuladas"
                ),
                "height": 12,
            }
        )

    for component in position.values():
        if not isinstance(component, dict):
            continue
        if component.get("type") != "CHART":
            continue
        chart_id = component.get("meta", {}).get("chartId")
        component["meta"]["height"] = (
            22 if chart_id in {2, 3, 4, 5, 6, 7} else 38
        )
        if chart_id == 19:
            component["meta"]["height"] = 48
        elif chart_id == 21:
            component["meta"]["height"] = 42

    # Coloca o heatmap junto das analises temporais, evitando uma segunda
    # pagina quase vazia na exportacao em PDF.
    grid_children = position["GRID_ID"]["children"]
    heatmap_row = "ROW-bVFRK36MSGXDuO0sPjWqW"
    if heatmap_row in grid_children:
        grid_children.remove(heatmap_row)
        temporal_row = "ROW-b5su73JqbVuwFN1NuxCk2"
        grid_children.insert(grid_children.index(temporal_row) + 1, heatmap_row)

    metadata["map_label_colors"] = {
        **metadata.get("map_label_colors", {}),
        "HIGH": "#E04355",
        "MEDIUM": "#F9A23F",
        "LOW": "#5AC189",
    }

    connection.execute(
        """
        UPDATE dashboards
        SET dashboard_title = ?, position_json = ?, json_metadata = ?,
            changed_on = ?
        WHERE id = ?
        """,
        (
            "Financial Risk & Fraud Analytics",
            json.dumps(position, ensure_ascii=False, separators=(",", ":")),
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            sqlite_datetime(),
            dashboard_id,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--dashboard-id", type=int, default=2)
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Banco do Superset nao encontrado: {database}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database.with_name(f"{database.name}.backup-{timestamp}")
    shutil.copy2(database, backup)

    try:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            refine_charts(connection)
            refine_dashboard(connection, args.dashboard_id)
            connection.commit()
    except Exception:
        shutil.copy2(backup, database)
        raise

    print(f"Dashboard {args.dashboard_id} refinado com sucesso.")
    print(f"Backup criado em: {backup}")


if __name__ == "__main__":
    main()
