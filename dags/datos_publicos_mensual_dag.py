"""DAG mensual de datos públicos (SMN oficial + serie propia).

Ejecuta `python -m actualizacion.run_mensual` dentro de la imagen
`public-data-etl:latest`. Carga los TXT mensuales oficiales del SMN y
recalcula la serie mensual propia (CALCULADO) para los años tocados.

Por defecto el runner procesa el año del intervalo y el anterior; aquí se fija
explícitamente el rango para que una re-ejecución de una fecha pasada use el
mismo periodo.

Al terminar exitosamente emite el Asset `datos_publicos_mensual_completo`.

Requisitos:
    - Este DAG debe estar despausado.
    - La imagen `public-data-etl:latest` debe existir en el host.
    - En producción, la identity de Infisical debe poder leer la carpeta
      `/datos_publicos_etl` del entorno `prod`.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk import Asset, DAG

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_mensual"

# Asset que emite este DAG al terminar la actualización completa.
ASSET_MENSUAL_COMPLETO = Asset("datos_publicos_mensual_completo")

with DAG(
    dag_id=DAG_ID,
    description=(
        "Actualización mensual: carga el TXT oficial del SMN y recalcula la "
        "serie mensual propia en DataLake.datos_publicos"
    ),
    schedule="0 7 3 * *",  # día 3 a las 07:00, hora de México
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),
    default_args={
        "owner": "etl",
        "retries": 2,
        "retry_delay": timedelta(minutes=15),
    },
    tags=["etl", "datos-publicos", "mensual"],
    doc_md=__doc__,
) as dag:
    actualizar = tarea_etl(
        "actualizar_datos_publicos_mensual",
        [
            "--desde",
            # Año del mes anterior (31 días atrás cubre cualquier fin de mes).
            "{{ (macros.ds_add((data_interval_end | ds), -31))[:4] }}",
            "--hasta",
            "{{ (data_interval_end | ds)[:4] }}",
        ],
        modulo="actualizacion.run_mensual",
        mem_limit="6g",
        timeout=timedelta(hours=4),
    )

    actualizar >> EmptyOperator(
        task_id="etl_completo",
        outlets=[ASSET_MENSUAL_COMPLETO],
    )
