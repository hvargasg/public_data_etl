"""Carga histórica de clima (disparo manual, normalmente una sola vez).

Ejecuta `python -m carga_inicial.backfill_clima` dentro de la imagen
`public-data-etl:latest`. Carga los diarios y mensuales oficiales del SMN desde
2023-01-01 y construye la serie mensual propia.

Es una operación costosa: puede tardar horas y descarga miles de archivos.
No se programa; se dispara manualmente desde la UI con los parámetros
`tipo` y `desde`.

Al terminar exitosamente emite el Asset `datos_publicos_backfill_completo`.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk import Asset, DAG, Param

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tags_datos_publicos, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_historico_manual"

ASSET_BACKFILL_COMPLETO = Asset("datos_publicos_backfill_completo")

with DAG(
    dag_id=DAG_ID,
    description="Carga histórica de clima 2023+ (disparo manual)",
    schedule=None,
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=14),
    default_args={
        "owner": "etl",
        "retries": 1,
        "retry_delay": timedelta(minutes=15),
    },
    params={
        "tipo": Param(
            "ambos",
            type="string",
            description="diario, mensual o ambos.",
        ),
        "desde": Param(
            "2023-01-01",
            type="string",
            description="Fecha inicial YYYY-MM-DD (mínimo 2023-01-01).",
        ),
    },
    tags=tags_datos_publicos("clima", "historico", "manual"),
    doc_md=__doc__,
) as dag:
    backfill = tarea_etl(
        "backfill_clima",
        [
            "--tipo",
            "{{ params.tipo }}",
            "--desde",
            "{{ params.desde }}",
        ],
        modulo="carga_inicial.backfill_clima",
        mem_limit="8g",
        timeout=timedelta(hours=12),
    )

    backfill >> EmptyOperator(
        task_id="etl_completo",
        outlets=[ASSET_BACKFILL_COMPLETO],
    )
