"""DAG diario: serie estatal desde la red reducida del SMN (CSV).

Ejecuta `python -m actualizacion.load_estatal_csv --auto` dentro de la imagen
`public-data-etl:latest`.

Comportamiento:

1. Calcula el mes anterior (el último mes cerrado).
2. Si ese mes ya está completo en `clima_estatal_mensual`, no descarga nada y
   solo sincroniza `dbo.clima_hist` si falta el mes.
3. Si falta, intenta descargar los CSV de TMax, TMed, TMin y Lluv.
   - Si aún no están publicados (404), termina en success y reintenta al día
     siguiente.
   - Si están, los agrega por entidad y los carga.
4. `dbo.clima_hist` se actualiza de forma **incremental**: solo agrega meses
   posteriores al último que ya tiene, o completa el último si está
   incompleto. No reescribe 2023+ en cada corrida.

Por eso el DAG corre a diario, pero después de cargar el mes nuevo se vuelve
un no-op (una consulta y salir) hasta el siguiente mes.

**Asset condicional.** Al terminar, el comando imprime `NUEVO_DATO=1` solo si
agregó filas nuevas a `dbo.clima_hist`. El DAG lee esa última línea y emite el
Asset `datos_publicos_estatal_nuevo` únicamente en ese caso. Los días no-op no
emiten nada, de modo que `exo_forecast_mensual` corre una vez por mes.

Carga histórica manual:

    sudo make estatal-csv ARGS="--todo"

Requisitos:
    - Este DAG debe estar despausado.
    - La imagen `public-data-etl:latest` debe existir en el host.
    - El catálogo `variable`, `fuente` y la tabla `clima_estatal_mensual` deben
      existir.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import ShortCircuitOperator
from airflow.sdk import Asset, DAG

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tags_datos_publicos, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_estatal_csv"

# Se emite solo cuando el comando reporta NUEVO_DATO=1.
ASSET_ESTATAL_NUEVO = Asset("datos_publicos_estatal_nuevo")


def _hay_datos_nuevos(ti) -> bool:
    """Lee la última línea del contenedor y decide si hubo mes nuevo."""
    salida = ti.xcom_pull(task_ids="actualizar_estatal_csv")
    return "NUEVO_DATO=1" in str(salida or "")


with DAG(
    dag_id=DAG_ID,
    description=(
        "Carga el mes anterior desde la red reducida del SMN cuando aparece; "
        "es idempotente y actualiza clima_hist de forma incremental"
    ),
    schedule="0 8 * * *",  # diario a las 08:00, hora de México
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={
        "owner": "etl",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=tags_datos_publicos("clima", "estatal", "diario"),
    doc_md=__doc__,
) as dag:
    actualizar = tarea_etl(
        "actualizar_estatal_csv",
        ["--auto"],
        modulo="actualizacion.load_estatal_csv",
        mem_limit="1g",
        timeout=timedelta(minutes=30),
        do_xcom_push=True,
        xcom_all=True,
    )

    decidir = ShortCircuitOperator(
        task_id="decidir_si_hay_datos_nuevos",
        python_callable=_hay_datos_nuevos,
    )

    actualizar >> decidir >> EmptyOperator(
        task_id="etl_completo",
        outlets=[ASSET_ESTATAL_NUEVO],
    )

