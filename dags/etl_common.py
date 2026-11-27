"""
Piezas compartidas por los DAGs del ETL de datos públicos. Un cambio de ruta,
de imagen o de límites se hace aquí, una sola vez.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import timedelta
from typing import Sequence

import pendulum
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

# --- Configuración del host (rutas del EC2, NO del contenedor de Airflow) ---
IMAGEN_ETL = "public-data-etl:latest"
REPO_HOST = os.getenv("ETL_REPO_HOST", "/opt/services/public_data_etl")
DATOS_HOST = f"{REPO_HOST}/data"
ENV_FILE_HOST = f"{REPO_HOST}/.env"
USUARIO_HOST = "1000:1000"  # uid:gid de 'ubuntu' (comando: id)
ZONA_HORARIA = "America/Mexico_City"  # ajústala a la tuya

# Dentro del contenedor el archivo de secretos NO termina en .env (ver la clase de abajo).
ENV_FILE_CONTENEDOR = "/run/secrets/etl_env"
# El repo vive en /app dentro de la imagen y data/ se monta en /app/data.
DIR_DATOS_CONTENEDOR = "/app/data"
DIR_TRABAJO_CONTENEDOR = "/app"

# --- Infisical (solo en el servidor de producción) ---
# El overlay de Airflow define INFISICAL_MACHINE_FILE y monta el archivo.
INFISICAL_MACHINE_FILE = os.getenv(
    "INFISICAL_MACHINE_FILE", "/run/secrets/infisical/machine.env"
)
# URL del servicio dentro de la red de Docker (no 127.0.0.1).
INFISICAL_DOMAIN = os.getenv(
    "INFISICAL_CONTAINER_API_URL", "http://infisical:8080"
)
INFISICAL_ENV = os.getenv("ETL_INFISICAL_ENV", "prod")
INFISICAL_PATH = os.getenv("ETL_INFISICAL_PATH", "/datos_publicos_etl")

# Red Docker opcional. Este ETL solo necesita salida a Internet (SMN, SIH,
# INEGI). Vacía = red por defecto de Docker.
RED_DOCKER = os.getenv("ETL_DOCKER_NETWORK", "") or None

FECHA_INICIO = pendulum.datetime(2026, 1, 1, tz=ZONA_HORARIA)

# Variables que el contenedor necesita para conectarse a SQL Server.
VARIABLES_REQUERIDAS = (
    "DB_SERVER",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
)


def usando_infisical() -> bool:
    """
    Indica de dónde salen los secretos.

    - Servidor: Airflow arranca con AIRFLOW_SECRETS_FROM_INFISICAL=true y monta
      machine.env, así que los secretos se consultan en Infisical.
    - Local: no existe machine.env; se mantiene el montaje del .env del proyecto.

    Se puede forzar con ETL_SECRETS_SOURCE=infisical|env.
    """
    modo = os.getenv("ETL_SECRETS_SOURCE", "auto").strip().lower()

    if modo == "infisical":
        return True

    if modo == "env":
        return False

    return (
        os.getenv("AIRFLOW_SECRETS_FROM_INFISICAL", "").strip().lower() == "true"
    )


def obtener_variables_infisical() -> dict[str, str]:
    """Autentica con Universal Auth y exporta los secretos del proyecto."""

    script = f"""
set -euo pipefail

set -a
source "{INFISICAL_MACHINE_FILE}"
set +a

TOKEN="$(infisical login \
    --method=universal-auth \
    --client-id="$INFISICAL_UNIVERSAL_AUTH_CLIENT_ID" \
    --client-secret="$INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET" \
    --domain="{INFISICAL_DOMAIN}" \
    --silent --plain)"

infisical export \
    --token="$TOKEN" \
    --domain="{INFISICAL_DOMAIN}" \
    --projectId="$INFISICAL_PROJECT_ID" \
    --env="{INFISICAL_ENV}" \
    --path="{INFISICAL_PATH}" \
    --format=json \
    --silent
"""

    try:
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Infisical no respondió a tiempo. "
            f"Revisa la red y el path {INFISICAL_PATH}."
        ) from exc

    if result.returncode != 0:
        # No mostrar stdout, stderr, token ni valores de secretos en los logs.
        raise RuntimeError(
            "No fue posible obtener los secretos de Infisical. "
            f"Código de salida: {result.returncode}. "
            f"Revisa la identidad, la red y el path {INFISICAL_PATH}."
        )

    try:
        data = json.loads(result.stdout)
        variables = {
            item["key"]: str(item["value"])
            for item in data
            if item.get("key") and item.get("value") is not None
        }
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError(
            "Infisical devolvió una respuesta JSON no válida."
        ) from exc

    faltantes = [clave for clave in VARIABLES_REQUERIDAS if not variables.get(clave)]

    if faltantes:
        raise RuntimeError(
            "Faltan variables en Infisical "
            f"({INFISICAL_ENV} {INFISICAL_PATH}): " + ", ".join(faltantes)
        )

    return variables


class DockerOperatorSinPlantillas(DockerOperator):
    """
    Airflow trata como archivo de plantilla cualquier texto que termine en .env, .sh o .bash
    (también dentro de `mounts` y `environment`) y falla con TemplateNotFound. Aquí se desactiva
    esa búsqueda de archivos; las expresiones {{ ... }} siguen funcionando.
    """

    template_ext = ()

    def execute(self, context):
        if usando_infisical():
            variables = obtener_variables_infisical()

            # En el servidor no se monta .env: los secretos llegan como variables
            # de entorno del contenedor, en el momento de ejecutar la tarea.
            self.mounts = [
                Mount(source=DATOS_HOST, target=DIR_DATOS_CONTENEDOR, type="bind"),
            ]
            self.environment = variables
            self.environment["ETL_DATA_DIR"] = DIR_DATOS_CONTENEDOR

        return super().execute(context)


def tarea_etl(
    task_id: str,
    comando: Sequence[str],
    *,
    modulo: str = "actualizacion.run_diario",
    mem_limit: str = "4g",
    timeout: timedelta = timedelta(hours=2),
    **kwargs,
) -> DockerOperatorSinPlantillas:
    """
    Tarea que corre un comando del ETL. Se usa dentro de un `with DAG(...)`.

    En local monta `REPO_HOST/.env`; en el servidor obtiene los secretos de
    Infisical al ejecutar la tarea (ver `DockerOperatorSinPlantillas.execute`).

    `modulo` permite ejecutar cualquiera de los entrypoints del repo:
        modulo="actualizacion.run_diario"   -> actualización diaria
        modulo="actualizacion.run_mensual"  -> actualización mensual
        modulo="carga_inicial.backfill_clima" -> carga histórica
        modulo="actualizacion.run_query"    -> query de control
    """
    return DockerOperatorSinPlantillas(
        task_id=task_id,
        image=IMAGEN_ETL,
        entrypoint=["python"],
        command=["-m", modulo, *comando],
        environment={
            "ETL_ENV_FILE": ENV_FILE_CONTENEDOR,
            "ETL_DATA_DIR": DIR_DATOS_CONTENEDOR,
        },
        working_dir=DIR_TRABAJO_CONTENEDOR,
        mounts=[
            Mount(source=DATOS_HOST, target=DIR_DATOS_CONTENEDOR, type="bind"),
            Mount(
                source=ENV_FILE_HOST,
                target=ENV_FILE_CONTENEDOR,
                type="bind",
                read_only=True,
            ),
        ],
        user=USUARIO_HOST,
        mem_limit=mem_limit,
        network_mode=RED_DOCKER,
        mount_tmp_dir=False,
        auto_remove="success",
        force_pull=False,
        do_xcom_push=False,
        execution_timeout=timeout,
        **kwargs,  # p. ej. retries=2, trigger_rule="all_done"
    )
