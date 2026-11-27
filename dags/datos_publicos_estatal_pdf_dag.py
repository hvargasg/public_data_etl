"""DAG mensual: resúmenes estatales mensuales del SMN (PDFs).

Ejecuta `python -m actualizacion.load_estatal_pdf` dentro de la imagen
`public-data-etl:latest`. Es el reemplazo del flujo legacy
`auto_conagua_download.py`:

1. Descarga los PDFs anuales de TMAX, TMED, TMIN y PREC.
2. Extrae la tabla estado-mes con `pdfplumber` (sin CSV intermedios).
3. Reemplaza en `datos_publicos.clima_estatal_mensual` los pares
   (año, variable) descargados, con `fuente_id = PDF_ESTATAL`.
4. Borra los PDFs temporales al terminar, incluso si hay error.

Por defecto procesa el año actual y el anterior (los PDFs se actualizan
mensualmente). Para una carga histórica completa:

    sudo make estatal-pdf ARGS="--todo"

No modifica `dbo.clima_hist`. La vista `vw_clima_hist_compat` reproduce el
formato ancho para 2023+.

Requisitos:
    - Este DAG debe estar despausado.
    - La imagen `public-data-etl:latest` debe existir en el host.
    - El catálogo `variable` y la tabla `clima_estatal_mensual` deben existir.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from airflow.sdk import DAG

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_estatal_pdf"

with DAG(
    dag_id=DAG_ID,
    description=(
        "Descarga y carga los resúmenes estatales mensuales del SMN "
        "(TMAX, TMED, TMIN, PREC) desde PDFs"
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
    tags=["etl", "datos-publicos", "mensual", "estatal", "pdf"],
    doc_md=__doc__,
) as dag:
    tarea_etl(
        "actualizar_estatal_pdf",
        [],
        modulo="actualizacion.load_estatal_pdf",
        mem_limit="1g",
        timeout=timedelta(hours=1),
    )
