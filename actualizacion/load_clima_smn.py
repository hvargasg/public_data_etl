"""Carga los TXT oficiales del SMN (mensuales y diarios).

Mensuales: cada archivo trae bloques por variable con una fila por año y
columnas ENE..DIC. Se cargan como OFICIAL / DEFINITIVO en clima_mensual.
Diarios: una fila por fecha con PRECIP, EVAP, TMAX y TMIN. Se cargan en
clima_diario como fuente SMN_TXT_DIARIO.

Ventana de carga: desde 2023-01-01 a la fecha. El archivo del SMN contiene
más historia, pero el ETL ignora todo lo anterior a 2023.

Uso:
    python -m actualizacion.load_clima_smn --tipo mensual
    python -m actualizacion.load_clima_smn --tipo diario --desde 2023-01-01
    python -m actualizacion.load_clima_smn --tipo ambos --clave 01001,01002 --limit 5
    python -m actualizacion.load_clima_smn --tipo mensual --dry-run
"""

from __future__ import annotations

import argparse
import calendar
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

from comun.constants import DESDE_MINIMO, clamp_desde
from comun.db import (
    get_engine,
    get_fuente_id,
    get_variable_map,
    insert_rows,
    log_carga,
    read_sql,
    render_sql,
)
from comun.utils import decode_text, normalize, parse_date, parse_float

# Títulos de bloque del TXT mensual -> código de variable homologada.
BLOQUES_MENSUAL = {
    "lluviatotalmensual": "PREC",
    "evaporacionmensual": "EVAP",
    "temperaturamaximapromedio": "TMAX",
    "temperaturaminimapromedio": "TMIN",
    "temperaturamediamensual": "TMED",
}

# Encabezados del TXT diario -> código de variable homologada.
TOKENS_DIARIO = {
    "PREC": ("precip", "precipitacion", "lluvia"),
    "EVAP": ("evap", "evaporacion"),
    "TMAX": ("tmax", "tempmax", "temperaturamaxima"),
    "TMIN": ("tmin", "tempmin", "temperaturaminima"),
    "TMED": ("tmed", "tempmedia", "temperaturamedia"),
}

SQL_DELETE_MENSUAL = """
DELETE FROM {{schema}}.clima_mensual
WHERE estacion_id = ?
  AND fuente_id = ?
  AND origen = 'OFICIAL'
  AND anio BETWEEN ? AND ?
"""

SQL_INSERT_MENSUAL = """
INSERT INTO {{schema}}.clima_mensual
    (estacion_id, variable_id, anio, mes, valor, origen, estado, fuente_id,
     dias_con_dato, dias_esperados, completo, fecha_corte)
VALUES (?, ?, ?, ?, ?, 'OFICIAL', 'DEFINITIVO', ?, ?, ?, ?, ?)
"""

SQL_DELETE_DIARIO = """
DELETE FROM {{schema}}.clima_diario
WHERE estacion_id = ?
  AND fuente_id = ?
  AND fecha BETWEEN ? AND ?
"""

SQL_INSERT_DIARIO = """
INSERT INTO {{schema}}.clima_diario
    (estacion_id, variable_id, fecha, valor, fuente_id, flag_calidad)
VALUES (?, ?, ?, ?, ?, 'OK')
"""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


# ----------------------------------------------------------------------------
# Parseo
# ----------------------------------------------------------------------------

def parse_meta(lines: list[str]) -> dict:
    """Extrae clave, emisión y situación del bloque de metadatos."""
    meta: dict = {"emision": None, "situacion": None}
    for line in lines[:40]:
        norm = normalize(line)
        if norm.startswith("emision"):
            meta["emision"] = parse_date(line.split(":", 1)[-1])
        elif norm.startswith("situacion"):
            meta["situacion"] = line.split(":", 1)[-1].strip()
    return meta


def _month_values(cells: list[str]) -> tuple[list[float | None], int | None]:
    """Devuelve los 12 valores mensuales y el conteo de meses con dato."""
    months = [parse_float(c) for c in cells[1:13]]
    months += [None] * (12 - len(months))
    meses = parse_float(cells[15]) if len(cells) > 15 else None
    if meses is None:
        meses = sum(1 for v in months if v is not None)
    return months, int(meses)


def parse_mensual(
    text: str,
    desde_anio: int,
    hasta_anio: int,
) -> tuple[list[tuple[str, int, int, float, int]], dict]:
    """Devuelve filas (variable, anio, mes, valor, dias_con_dato) y metadatos."""
    lines = text.splitlines()
    meta = parse_meta(lines)
    rows: list[tuple[str, int, int, float, int]] = []

    current: str | None = None
    in_table = False

    for line in lines:
        norm = normalize(line)
        if norm in BLOQUES_MENSUAL:
            current = BLOQUES_MENSUAL[norm]
            in_table = False
            continue

        if current is None:
            continue

        if not in_table:
            # Encabezado de la tabla: AÑO, ENE, FEB, ... DIC
            if "ene" in norm and "feb" in norm and "dic" in norm:
                in_table = True
            continue

        if not line.strip():
            current = None
            in_table = False
            continue

        cells = [c.strip() for c in line.split("\t")]
        if not cells or not re.fullmatch(r"\d{4}", cells[0]):
            continue  # filas de resumen: MÍNIMA, MÁXIMA, MEDIA, DESV.ST

        anio = int(cells[0])
        if anio < desde_anio or anio > hasta_anio:
            continue

        months, meses = _month_values(cells)
        for mes, valor in enumerate(months, start=1):
            if valor is not None:
                rows.append((current, anio, mes, valor, meses))

    return rows, meta


def parse_diario(
    text: str,
    desde: date,
    hasta: date,
) -> tuple[list[tuple[str, date, float]], dict]:
    """Devuelve filas (variable, fecha, valor) y metadatos."""
    lines = text.splitlines()
    meta = parse_meta(lines)
    rows: list[tuple[str, date, float]] = []

    header_index = None
    for i, line in enumerate(lines):
        if "fecha" in normalize(line):
            header_index = i
            break
    if header_index is None:
        return rows, meta

    # El encabezado del SMN trae una columna vacía extra tras FECHA
    # ("FECHA\t\tPRECIP...") que las filas de datos no tienen. Se compacta
    # para que los índices coincidan con los valores.
    header = [
        normalize(c)
        for c in lines[header_index].split("\t")
        if c.strip()
    ]
    mapping: dict[str, int] = {}
    for variable, tokens in TOKENS_DIARIO.items():
        for i, name in enumerate(header):
            if any(token in name for token in tokens):
                mapping[variable] = i
                break

    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("\t")]
        if not cells:
            continue
        fecha = parse_date(cells[0])
        if fecha is None:
            continue  # línea de unidades (mm, °C) u otra basura
        if fecha < desde or fecha > hasta:
            continue
        for variable, index in mapping.items():
            if index >= len(cells):
                continue
            valor = parse_float(cells[index])
            if valor is not None:
                rows.append((variable, fecha, valor))

    return rows, meta


# ----------------------------------------------------------------------------
# Descarga
# ----------------------------------------------------------------------------

def fetch(url: str, timeout: int) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return decode_text(response.content)


def cargar_mensual(
    engine,
    estaciones,
    variable_map: dict[str, int],
    fuente_id: int,
    desde_anio: int,
    hasta_anio: int,
    timeout: int,
    workers: int,
    dry_run: bool,
) -> tuple[int, int]:
    total = 0
    errores = 0

    def work(row):
        url = row.url_mensual
        if not isinstance(url, str) or not url:
            return row.estacion_id, [], None
        try:
            text = fetch(url, timeout)
        except Exception as exc:  # noqa: BLE001
            return row.estacion_id, [], f"descarga: {exc}"
        rows, meta = parse_mensual(text, desde_anio, hasta_anio)
        return row.estacion_id, (rows, meta), None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, row) for row in estaciones.itertuples(index=False)]
        for future in as_completed(futures):
            estacion_id, payload, error = future.result()
            if error:
                errores += 1
                print(f"  ! estación {estacion_id}: {error}")
                continue
            if not payload:
                continue
            rows, meta = payload
            corte = meta.get("emision") or date.today()

            values = []
            for variable, anio, mes, valor, meses in rows:
                variable_id = variable_map.get(variable)
                if variable_id is None:
                    continue
                esperados = calendar.monthrange(anio, mes)[1]
                # El TXT mensual no informa días con dato (la columna MESES
                # cuenta meses del año, no días). Se deja NULL y se marca
                # completo = NULL; la completitud real solo se conoce con los
                # diarios y la calcula build_mensual para las filas CALCULADO.
                values.append(
                    (
                        estacion_id,
                        variable_id,
                        anio,
                        mes,
                        valor,
                        fuente_id,
                        None,
                        esperados,
                        None,
                        corte,
                    )
                )
            if not values:
                continue
            total += len(values)
            if dry_run:
                continue
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    render_sql(SQL_DELETE_MENSUAL),
                    (estacion_id, fuente_id, desde_anio, hasta_anio),
                )
            insert_rows(engine, SQL_INSERT_MENSUAL, values)

    return total, errores


def cargar_diario(
    engine,
    estaciones,
    variable_map: dict[str, int],
    fuente_id: int,
    desde: date,
    hasta: date,
    timeout: int,
    workers: int,
    dry_run: bool,
) -> tuple[int, int]:
    total = 0
    errores = 0

    def work(row):
        url = row.url_diario
        if not isinstance(url, str) or not url:
            return row.estacion_id, [], None
        try:
            text = fetch(url, timeout)
        except Exception as exc:  # noqa: BLE001
            return row.estacion_id, [], f"descarga: {exc}"
        rows, _ = parse_diario(text, desde, hasta)
        return row.estacion_id, rows, None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, row) for row in estaciones.itertuples(index=False)]
        for future in as_completed(futures):
            estacion_id, rows, error = future.result()
            if error:
                errores += 1
                print(f"  ! estación {estacion_id}: {error}")
                continue
            values = [
                (estacion_id, variable_map[v], f, valor, fuente_id)
                for v, f, valor in rows
                if v in variable_map
            ]
            if not values:
                continue
            total += len(values)
            if dry_run:
                continue
            with engine.begin() as conn:
                conn.exec_driver_sql(render_sql(SQL_DELETE_DIARIO), (estacion_id, fuente_id, desde, hasta))
            insert_rows(engine, SQL_INSERT_DIARIO, values)

    return total, errores


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Carga los TXT oficiales del SMN.")
    parser.add_argument("--tipo", choices=("mensual", "diario", "ambos"), default="mensual")
    parser.add_argument("--clave", default="", help="Claves SMN separadas por coma; vacío = todas.")
    parser.add_argument("--desde", default=None, help="YYYY-MM-DD (diario) o YYYY (mensual).")
    parser.add_argument("--hasta", default=None, help="YYYY-MM-DD (diario) o YYYY (mensual).")
    parser.add_argument("--dias", type=int, default=30,
                        help="Para diario sin --desde: últimos N días (default 30).")
    parser.add_argument("--limit", type=int, default=0, help="Limita el número de estaciones.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hoy = date.today()

    def as_desde(value: str | None, default: date) -> date:
        if not value:
            return default
        if len(value) == 4:
            return date(int(value), 1, 1)
        return parse_date(value) or default

    def as_hasta(value: str | None, default: date) -> date:
        if not value:
            return default
        if len(value) == 4:
            return date(int(value), 12, 31)
        return parse_date(value) or default

    hasta = as_hasta(args.hasta, hoy)
    desde_solicitado = as_desde(args.desde, DESDE_MINIMO)
    if desde_solicitado < DESDE_MINIMO:
        print(
            f"Aviso: la ventana mínima es {DESDE_MINIMO}; "
            f"se ignora el histórico anterior y se carga desde {DESDE_MINIMO}."
        )
    desde_mensual = clamp_desde(desde_solicitado)
    desde_diario = clamp_desde(
        as_desde(args.desde, hasta - timedelta(days=max(1, args.dias) - 1))
    )
    if desde_diario > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    desde_anio, hasta_anio = desde_mensual.year, hasta.year

    engine = get_engine()
    variable_map = get_variable_map(engine)
    fuente_mensual = get_fuente_id(engine, "SMN_TXT_MENSUAL")
    fuente_diario = get_fuente_id(engine, "SMN_TXT_DIARIO")

    claves = [c.strip() for c in args.clave.split(",") if c.strip()]
    sql = "SELECT estacion_id, clave_smn, url_mensual, url_diario FROM {{schema}}.estacion"
    if claves:
        safe = ",".join("'" + c.replace("'", "''") + "'" for c in claves)
        sql += f" WHERE clave_smn IN ({safe})"
    sql += " ORDER BY clave_smn"
    estaciones = read_sql(engine, sql)
    if args.limit:
        estaciones = estaciones.head(args.limit)

    if estaciones.empty:
        print("No hay estaciones cargadas. Ejecuta primero load_estaciones.")
        return 1

    print(f"Estaciones: {len(estaciones)} | tipo: {args.tipo}")
    fallos = 0

    if args.tipo in ("mensual", "ambos"):
        print(f"Mensual oficial: años {desde_anio}..{hasta_anio}")
        with log_carga(engine, "load_clima_smn_mensual", "SMN_TXT_MENSUAL") as info:
            filas, errores = cargar_mensual(
                engine, estaciones, variable_map, fuente_mensual,
                desde_anio, hasta_anio, args.timeout, args.workers, args.dry_run,
            )
            info["filas"] = filas
        print(f"  filas mensuales: {filas:,}")
        if filas == 0 and errores > 0:
            fallos += 1

    if args.tipo in ("diario", "ambos"):
        print(f"Diario oficial: {desde_diario} -> {hasta}")
        with log_carga(engine, "load_clima_smn_diario", "SMN_TXT_DIARIO") as info:
            filas, errores = cargar_diario(
                engine, estaciones, variable_map, fuente_diario,
                desde_diario, hasta, args.timeout, args.workers, args.dry_run,
            )
            info["filas"] = filas
        print(f"  filas diarias: {filas:,}")
        if filas == 0 and errores > 0:
            fallos += 1

    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
