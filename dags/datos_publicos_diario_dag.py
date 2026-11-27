"""DAG diario de datos públicos (SMN + serie mensual propia).

Ejecuta `python -m actualizacion.run_diario` dentro de la imagen
`public-data-etl:latest`. La ventana cubre los últimos 7 días del intervalo
lógico, para tolerar que el SMN publique con retraso.

El runner carga los TXT diarios del SMN y recalcula la serie mensual propia de
los meses tocados. Las cargas son idempotentes por estación y rango de fechas.

Al terminar exitosamente emite el Asset `datos_publicos_diario_completo` para
que otros DAGs o consumidores puedan encadenarse.

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

DAG_ID = "datos_publicos_diario"

# Asset que emite este DAG al terminar la actualización completa.
ASSET_DIARIO_COMPLETO = Asset("datos_publicos_diario_completo")

with DAG(
    dag_id=DAG_ID,
    description=(
        "Actualización diaria de datos públicos: clima SMN y serie mensual "
        "propia (SQL Server -> DataLake.datos_publicos)"
    ),
    schedule="0 6 * * *",  # 06:00, hora de México
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),
    default_args={
        "owner": "etl",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["etl", "datos-publicos", "diario"],
    doc_md=__doc__,
) as dag:
    # data_interval_end = fecha de la corrida; se procesan los 7 días previos.
    actualizar = tarea_etl(
        "actualizar_datos_publicos",
        [
            "--desde",
            "{{ macros.ds_add((data_interval_end | ds), -6) }}",
            "--hasta",
            "{{ data_interval_end | ds }}",
        ],
        modulo="actualizacion.run_diario",
        mem_limit="4g",
        timeout=timedelta(hours=2, minutes=30),
    )

    # Marca de "todo terminó bien": emite el asset solo si la carga tuvo éxito.
    actualizar >> EmptyOperator(
        task_id="etl_completo",
        outlets=[ASSET_DIARIO_COMPLETO],
    )
