#!/usr/bin/env bash
# Ejecuta un comando del ETL dentro de su imagen Docker resolviendo los secretos
# de dos formas:
#
#   env        (desarrollo) -> monta el .env del repositorio.
#   infisical  (servidor)   -> descarga la carpeta configurada de Infisical y la
#                              pasa al contenedor con --env-file.
#
# El modo por defecto es "auto":
#   - si existe /etc/infisical/machine.env -> infisical
#   - si no existe                         -> env
#
# Se puede forzar con SECRETS_SOURCE=env|infisical (en el entorno o en .env).
#
# Uso:
#   ./scripts/etl-infisical.sh --dias 7
#   ETL_MODULO=actualizacion.run_mensual ./scripts/etl-infisical.sh --completo
#   ETL_MODULO=carga_inicial.run_inicial ./scripts/etl-infisical.sh --init
#   ETL_MODULO=actualizacion.run_query ./scripts/etl-infisical.sh \
#       --archivo actualizacion/queries/01_vigente.sql
#   ETL_DATA=/tmp/etl_prueba ./scripts/etl-infisical.sh --help
#
# Variables:
#   ETL_MODULO                módulo a ejecutar (por defecto actualizacion.run_diario)
#   SECRETS_SOURCE            env | infisical | auto (por defecto: auto)
#   INFISICAL_MACHINE_FILE    credenciales de la identity (por defecto /etc/infisical/machine.env)
#   INFISICAL_ENV             entorno de Infisical (por defecto: prod)
#   INFISICAL_PATH            carpeta de secretos (por defecto: /datos_publicos_etl)
#   ETL_IMAGE                 imagen a ejecutar (por defecto public-data-etl:latest)
#   ETL_DATA                  datos locales a montar en /app/data (por defecto ./data)
#   ETL_UID                   usuario:grupo del contenedor (por defecto 1000:1000)
#   ETL_DOCKER_NETWORK        red Docker opcional (vacía = red por defecto)
#
# Requiere jq en el host para convertir el JSON de Infisical a --env-file.

set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
IMAGE="${ETL_IMAGE:-public-data-etl:latest}"
DATA_DIR="${ETL_DATA:-$REPO_DIR/data}"
RUN_USER="${ETL_UID:-1000:1000}"
MODULO="${ETL_MODULO:-actualizacion.run_diario}"

# Lee una clave simple del .env sin exportar el resto de secretos.
dotenv_get() {
    local key="$1"
    [[ -f "$ENV_FILE" ]] || return 0
    sed -n "s/^[[:space:]]*${key}=//p" "$ENV_FILE" | tail -n 1 \
        | tr -d '\r' \
        | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

SECRETS_SOURCE="${SECRETS_SOURCE:-$(dotenv_get SECRETS_SOURCE)}"
SECRETS_SOURCE="${SECRETS_SOURCE:-auto}"
MACHINE_FILE="${INFISICAL_MACHINE_FILE:-$(dotenv_get INFISICAL_MACHINE_FILE)}"
MACHINE_FILE="${MACHINE_FILE:-/etc/infisical/machine.env}"

if [[ "$SECRETS_SOURCE" == "auto" ]]; then
    if [[ -e "$MACHINE_FILE" ]]; then
        SECRETS_SOURCE=infisical
    else
        SECRETS_SOURCE=env
    fi
fi

if [[ ! -d "$DATA_DIR" ]]; then
    printf '[etl] ERROR: no existe la carpeta de datos %s\n' "$DATA_DIR" >&2
    printf '[etl] Créala o ajusta ETL_DATA.\n' >&2
    exit 1
fi

DOCKER_ARGS=(
    run --rm
    --user "$RUN_USER"
    --entrypoint python
    --workdir /app
    --mount "type=bind,source=$DATA_DIR,target=/app/data"
)

# Red Docker opcional. Este ETL solo necesita salida a Internet (SMN, SIH,
# INEGI), pero se permite unir el contenedor a una red existente.
ETL_NETWORK="${ETL_DOCKER_NETWORK:-$(dotenv_get ETL_DOCKER_NETWORK)}"
if [[ -n "$ETL_NETWORK" ]]; then
    if docker network inspect "$ETL_NETWORK" >/dev/null 2>&1; then
        DOCKER_ARGS+=(--network "$ETL_NETWORK")
    else
        printf '[etl] AVISO: no existe la red %s; se usa la red por defecto.\n' \
            "$ETL_NETWORK" >&2
    fi
fi

case "$SECRETS_SOURCE" in
    env)
        if [[ -f "$ENV_FILE" ]]; then
            DOCKER_ARGS+=(
                --mount "type=bind,source=$ENV_FILE,target=/run/secrets/etl_env,readonly"
                -e ETL_ENV_FILE=/run/secrets/etl_env
            )
        else
            printf '[etl] AVISO: no existe %s; solo funcionarán los comandos que no necesiten secretos.\n' \
                "$ENV_FILE" >&2
            printf '[etl] Crea uno con: make env\n' >&2
        fi
        exec docker "${DOCKER_ARGS[@]}" "$IMAGE" -m "$MODULO" "$@"
        ;;
    infisical)
        if ! command -v infisical >/dev/null 2>&1; then
            printf '[etl] ERROR: falta el CLI de Infisical en el host.\n' >&2
            printf '[etl] Instálalo o usa SECRETS_SOURCE=env para desarrollo.\n' >&2
            exit 1
        fi
        if [[ ! -r "$MACHINE_FILE" ]]; then
            printf '[etl] ERROR: modo infisical pero no puedo leer %s\n' "$MACHINE_FILE" >&2
            printf '[etl] Ejecuta con sudo (sudo make diario ...) o usa SECRETS_SOURCE=env.\n' >&2
            exit 1
        fi

        # shellcheck disable=SC1090
        set -a
        source "$MACHINE_FILE"
        set +a

        : "${INFISICAL_PROJECT_ID:?falta INFISICAL_PROJECT_ID en machine.env}"

        # Se aceptan los nombres de Universal Auth y los nombres cortos.
        CLIENT_ID_VALUE="${INFISICAL_UNIVERSAL_AUTH_CLIENT_ID:-${INFISICAL_CLIENT_ID:-}}"
        CLIENT_SECRET_VALUE="${INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET:-${INFISICAL_CLIENT_SECRET:-}}"
        : "${CLIENT_ID_VALUE:?falta INFISICAL_UNIVERSAL_AUTH_CLIENT_ID en machine.env}"
        : "${CLIENT_SECRET_VALUE:?falta INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET en machine.env}"

        export INFISICAL_API_URL="${INFISICAL_API_URL:-$(dotenv_get INFISICAL_API_URL)}"
        export INFISICAL_API_URL="${INFISICAL_API_URL:-http://127.0.0.1:8081}"

        INFISICAL_ENV="${INFISICAL_ENV:-$(dotenv_get INFISICAL_ENV)}"
        INFISICAL_ENV="${INFISICAL_ENV:-prod}"
        INFISICAL_PATH="${INFISICAL_PATH:-$(dotenv_get INFISICAL_PATH)}"
        INFISICAL_PATH="${INFISICAL_PATH:-/datos_publicos_etl}"
        # La CLI acepta la ruta con o sin barra final; normalizamos.
        [[ "$INFISICAL_PATH" == "/" ]] || INFISICAL_PATH="${INFISICAL_PATH%/}"

        printf '[etl] secretos: Infisical (env=%s, path=%s)\n' \
            "$INFISICAL_ENV" "$INFISICAL_PATH" >&2

        if [[ -z "${INFISICAL_TOKEN:-}" ]]; then
            INFISICAL_TOKEN="$(infisical login --method=universal-auth \
                --client-id="$CLIENT_ID_VALUE" \
                --client-secret="$CLIENT_SECRET_VALUE" \
                --domain="$INFISICAL_API_URL" \
                --silent --plain)"
            export INFISICAL_TOKEN
        fi

        # La credencial de la identity no debe llegar al contenedor.
        unset INFISICAL_UNIVERSAL_AUTH_CLIENT_ID INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET \
            INFISICAL_CLIENT_ID INFISICAL_CLIENT_SECRET \
            CLIENT_ID_VALUE CLIENT_SECRET_VALUE

        if ! command -v jq >/dev/null 2>&1; then
            printf '[etl] ERROR: falta jq en el host para convertir los secretos.\n' >&2
            exit 1
        fi

        # Archivos temporales: docker --env-file no admite valores multilínea y
        # el formato dotenv de Infisical puede incluir comillas que Docker no
        # elimina. Se exporta JSON y se convierte a KEY=valor literal.
        umask 077
        SECRETS_JSON="$(mktemp "${TMPDIR:-/tmp}/etl-secrets.XXXXXX.json")"
        SECRETS_FILE="$(mktemp "${TMPDIR:-/tmp}/etl-secrets.XXXXXX.env")"
        trap 'rm -f "$SECRETS_FILE" "$SECRETS_JSON"' EXIT

        infisical export \
            --domain="$INFISICAL_API_URL" \
            --projectId="$INFISICAL_PROJECT_ID" \
            --env="$INFISICAL_ENV" \
            --path="$INFISICAL_PATH" \
            --format=json \
            --silent > "$SECRETS_JSON"

        if ! jq -e '
            type == "array" and
            all(.[];
                (.key | type) == "string" and
                .value != null and
                (((.value | tostring) | test("[\\r\\n]")) | not)
            )
        ' "$SECRETS_JSON" >/dev/null; then
            printf '[etl] ERROR: Infisical devolvió un JSON no válido o con valores multilínea.\n' >&2
            exit 1
        fi

        jq -r '.[] | select(.key != null and .value != null) | "\(.key)=\(.value)"' \
            "$SECRETS_JSON" > "$SECRETS_FILE"

        faltantes=()
        for clave in DB_SERVER DB_NAME DB_USER DB_PASSWORD; do
            grep -q "^${clave}=" "$SECRETS_FILE" || faltantes+=("$clave")
        done

        if ((${#faltantes[@]})); then
            printf '[etl] ERROR: faltan secretos en Infisical (%s %s): %s\n' \
                "$INFISICAL_ENV" "$INFISICAL_PATH" "${faltantes[*]}" >&2
            exit 1
        fi

        # Sin exec: el trap debe borrar el archivo temporal al terminar.
        docker "${DOCKER_ARGS[@]}" --env-file "$SECRETS_FILE" "$IMAGE" -m "$MODULO" "$@"
        ;;
    *)
        printf '[etl] ERROR: SECRETS_SOURCE inválido: %s (usa env o infisical)\n' \
            "$SECRETS_SOURCE" >&2
        exit 1
        ;;
esac
