#!/usr/bin/env bash
# Atajos para operar el ETL desde la terminal del servidor.
#
# Uso (una vez por sesión):   source /opt/services/public_data_etl/scripts/etl-helpers.sh
# Para que se carguen siempre: añade esa misma línea a ~/.bashrc
#
#   etl <comando ...>                  corre un módulo del ETL (.env o Infisical)
#   diario <opciones ...>              actualización diaria (SMN + serie mensual)
#   mensual <opciones ...>             actualización mensual (oficial + propia)
#   inicial <opciones ...>             estructuras, geografía, sitios, etc.
#   backfill <opciones ...>            carga histórica de clima 2023+
#   consulta <archivo.sql>             ejecuta una query de control
#
# `etl` delega en scripts/etl-infisical.sh: usa .env en desarrollo y la
# Machine Identity de Infisical cuando existe /etc/infisical/machine.env.

# La raíz del repo se deduce de la ubicación de este archivo
ETL_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ETL_REPO
export ETL_IMAGE="${ETL_IMAGE:-public-data-etl:latest}"

etl() {
  local script="$ETL_REPO/scripts/etl-infisical.sh"
  local machine_file="${INFISICAL_MACHINE_FILE:-/etc/infisical/machine.env}"

  # En el servidor machine.env suele ser root:640; se reintenta con sudo.
  if [ -e "$machine_file" ] && [ ! -r "$machine_file" ]; then
    local envs=()
    local var
    for var in SECRETS_SOURCE INFISICAL_MACHINE_FILE INFISICAL_ENV INFISICAL_PATH \
        ETL_DATA ETL_IMAGE ETL_UID ETL_DOCKER_NETWORK ETL_MODULO; do
      if [ -n "${!var:-}" ]; then
        envs+=("$var=${!var}")
      fi
    done
    sudo env "${envs[@]}" "$script" "$@"
  else
    "$script" "$@"
  fi
}

diario() {
  ETL_MODULO=actualizacion.run_diario etl "$@"
}

mensual() {
  ETL_MODULO=actualizacion.run_mensual etl "$@"
}

inicial() {
  ETL_MODULO=carga_inicial.run_inicial etl "$@"
}

backfill() {
  ETL_MODULO=carga_inicial.backfill_clima etl "$@"
}

consulta() {   # uso: consulta actualizacion/queries/01_vigente.sql [--limite 50]
  local archivo="${1:-actualizacion/queries/01_vigente.sql}"
  shift || true
  ETL_MODULO=actualizacion.run_query etl --archivo "$archivo" "$@"
}
