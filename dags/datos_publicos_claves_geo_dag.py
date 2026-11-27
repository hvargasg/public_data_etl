"""DAG diario: claves geográficas oficiales para dbo.Clientes y dbo.CEDIS.

Ejecuta `python -m actualizacion.load_claves_geo` dentro de la imagen
`public-data-etl:latest`. El módulo solo rellena las filas que aún tienen
`cvegeo`/`cve_ent` en NULL, por lo que la corrida diaria procesa únicamente
los registros nuevos.

El cálculo geométrico ocurre en SQL Server usando los índices espaciales de
`DataLake.datos_publicos.municipio` y `.entidad`; el contenedor solo orquesta
por lotes.

Requisitos:
    - Este DAG debe estar despausado.
    - La imagen `public-data-etl:latest` debe existir en el host.
    - Las tablas `dbo.Clientes` y `dbo.CEDIS` deben existir.
    - La geografía INEGI debe estar cargada en `DataLake.datos_publicos`.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from airflow.sdk import DAG

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_claves_geo"

with DAG(
    dag_id=DAG_ID,
    description=(
        "Asigna cvegeo (municipio) y cve_ent (estado) a dbo.Clientes y "
        "dbo.CEDIS con el Marco Geoestadístico INEGI"
    ),
    schedule="0 2 * * *",  # 02:00, hora de México
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    default_args={
        "owner": "etl",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["etl", "datos-publicos", "diario", "geografia"],
    doc_md=__doc__,
) as dag:
    tarea_etl(
        "actualizar_claves_geo",
        [],
        modulo="actualizacion.load_claves_geo",
        mem_limit="1g",
        timeout=timedelta(hours=1, minutes=30),
    )
