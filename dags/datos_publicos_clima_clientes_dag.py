"""DAG diario: clima derivado para las ubicaciones de clientes.

Ejecuta `python -m actualizacion.build_clima_clientes` dentro de la imagen
`public-data-etl:latest`. El módulo:

1. Sincroniza las celdas de ~1 km y el enlace cliente-domicilio -> celda
   desde `dbo.Clientes`.
2. Construye el puente `cliente_estacion` con las 5 estaciones OPERANDO más
   cercanas a cada celda (se refresca solo cada 30 días).
3. Recalcula el clima mensual derivado (NEAREST e IDW) de los últimos 2 meses
   desde `vw_clima_mensual_vigente`.

No guarda clima diario por cliente: para eso están las vistas
`vw_clima_cliente_diario` y `vw_clima_cliente_diario_cercano`.

Requisitos:
    - Este DAG debe estar despausado.
    - La imagen `public-data-etl:latest` debe existir en el host.
    - `dbo.Clientes` debe tener `Lat`/`Lon` y, preferentemente, `cvegeo`/`cve_ent`
      (los llena `datos_publicos_claves_geo`, que corre antes a las 02:00).
    - La geografía INEGI y las estaciones deben estar cargadas.

Una carga histórica completa se hace a mano con:

    sudo make clima-clientes ARGS="--todo --recalcular-puente"
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from airflow.sdk import DAG

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar etl_common
from etl_common import FECHA_INICIO, tarea_etl  # noqa: E402

DAG_ID = "datos_publicos_clima_clientes"

with DAG(
    dag_id=DAG_ID,
    description=(
        "Deriva clima mensual (NEAREST/IDW) para las ubicaciones de "
        "dbo.Clientes desde las estaciones OPERANDO más cercanas"
    ),
    schedule="0 3 * * *",  # 03:00, hora de México; después de claves_geo (02:00)
    start_date=FECHA_INICIO,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),
    default_args={
        "owner": "etl",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["etl", "datos-publicos", "diario", "geografia", "clientes"],
    doc_md=__doc__,
) as dag:
    tarea_etl(
        "actualizar_clima_clientes",
        [],
        modulo="actualizacion.build_clima_clientes",
        mem_limit="2g",
        timeout=timedelta(hours=2),
    )
