"""DAG mensual: serie estatal desde la red reducida del SMN (CSV).

Ejecuta `python -m actualizacion.load_estatal_csv` dentro de la imagen
`public-data-etl:latest`. Es la fuente operativa de la serie estatal:

1. Descarga los CSV mensuales de TMax, TMed, TMin y Lluv.
2. Agrega por entidad federativa (media simple de estaciones).
3. Hace *upsert* en `datos_publicos.clima_estatal_mensual` con
   `fuente_id = SMN_RED_CSV`.
4. No escribe archivos: todo se parsea en memoria.

Por defecto procesa los últimos 3 meses. Para una carga histórica completa:

    sudo make estatal-csv ARGS="--todo"

La vista `vw_clima_estatal_vigente` prioriza el CSV y usa `PDF_ESTATAL` solo
si falta el mes. El loader de PDFs (`datos_publicos_estatal_pdf`) queda como
legacy/opcional y está pausado.

Diferencias documentadas en `docs/fuentes.md`:
    - temperatura: prácticamente idéntica al PDF (±0.3 °C);
    - lluvia: estimación de la red reducida, difiere ~5–25% del PDF oficial.

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

from airflow.sdk import DAG

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_estatal_csv"

with DAG(
    dag_id=DAG_ID,
    description=(
        "Carga la serie estatal mensual desde la red reducida del SMN "
        "(TMax, TMed, TMin, Lluv) en CSV"
    ),
    schedule="0 8 6 * *",  # día 6 a las 08:00, hora de México
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    default_args={
        "owner": "etl",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["etl", "datos-publicos", "mensual", "estatal", "csv"],
    doc_md=__doc__,
) as dag:
    tarea_etl(
        "actualizar_estatal_csv",
        [],
        modulo="actualizacion.load_estatal_csv",
        mem_limit="1g",
        timeout=timedelta(hours=1),
    )
