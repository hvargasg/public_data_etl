"""Descarga los CSV diarios del SIH y los carga en `clima_diario`.

Ventana de carga: 2023-01-01 a la fecha. No se carga el histórico anterior.

Los encabezados del SIH son heterogéneos: se detectan por nombre normalizado.
Se descarga en paralelo, se parsea y luego se escribe de forma secuencial.

Uso:
    python -m actualizacion.load_clima_sih --desde 2023-01-01 --hasta 2025-12-31
    python -m actualizacion.load_clima_sih --dias 30 --workers 6
    python -m actualizacion.load_clima_sih --clave AGSAG,C01001 --desde 2023-01-01
"""

from __future__ import annotations

import argparse
import csv
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests

from comun.constants import DESDE_MINIMO, clamp_desde
from comun.db import get_engine, get_fuente_id, get_variable_map, insert_rows, log_carga, read_sql, render_sql
from comun.utils import decode_text, find_header, normalize, parse_date, parse_float

BASE_URL = "https://sih.conagua.gob.mx/basedatos/Climas/{clave}.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,text/plain,*/*",
}

SQL_DELETE = """
DELETE FROM {{schema}}.clima_diario
WHERE estacion_id = ? AND fuente_id = ? AND fecha BETWEEN ? AND ?
"""

SQL_INSERT = """
INSERT INTO {{schema}}.clima_diario
    (estacion_id, variable_id, fecha, valor, fuente_id, flag_calidad)
VALUES (?, ?, ?, ?, ?, ?)
"""

VARIABLE_TOKENS = {
    "PREC": ("precipitacion", "precip", "lluvia"),
    "TMAX": ("tempmax", "temperaturamaxima", "tmax"),
    "TMIN": ("tempmin", "temperaturaminima", "tmin"),
    "TMED": ("tempmedia", "temperaturamedia", "tempamb", "tmed"),
    "EVAP": ("evaporacion", "evap"),
}


def build_header_map(header: list[str]) -> dict[str, int]:
    normalized = [normalize(h) for h in header]
    result: dict[str, int] = {}
    for variable, tokens in VARIABLE_TOKENS.items():
        for i, name in enumerate(normalized):
            if any(token in name for token in tokens):
                result[variable] = i
                break
    return result


def fetch_and_parse(
    clave: str,
    desde: date,
    hasta: date,
    timeout: int,
    archivo_dir: Path | None = None,
) -> tuple[str, list[tuple], str | None]:
    if archivo_dir is not None:
        path = archivo_dir / f"{clave}.csv"
        if not path.exists():
            return clave, [], f"no existe {path}"
        raw = path.read_bytes()
    else:
        url = BASE_URL.format(clave=clave)
        try:
            response = requests.get(
                url, headers=HEADERS, timeout=timeout, allow_redirects=True
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return clave, [], f"descarga: {exc}"

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" in content_type or response.content.lstrip()[:1] == b"<":
            return clave, [], "respuesta HTML (posible bloqueo o página JS)"
        raw = response.content

    text = decode_text(raw)
    lines = text.splitlines()
    header_index = find_header(lines)
    if header_index is None:
        return clave, [], "sin encabezado reconocible"

    reader = csv.reader(io.StringIO("\n".join(lines[header_index:])))
    header = next(reader)
    mapping = build_header_map(header)
    if "fecha" not in [normalize(h) for h in header]:
        return clave, [], "sin columna Fecha"

    fecha_idx = next(i for i, h in enumerate(header) if normalize(h) == "fecha")
    rows: dict[tuple[str, date], float] = {}
    for raw in reader:
        if len(raw) <= fecha_idx:
            continue
        fecha = parse_date(raw[fecha_idx])
        if fecha is None or fecha < desde or fecha > hasta:
            continue
        for variable, index in mapping.items():
            if index >= len(raw):
                continue
            valor = parse_float(raw[index])
            if valor is not None:
                rows[(variable, fecha)] = valor

    return clave, [(v, f, val) for (v, f), val in rows.items()], None


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga CSV diarios del SIH.")
    parser.add_argument("--desde", default=None, help="YYYY-MM-DD")
    parser.add_argument("--hasta", default=None, help="YYYY-MM-DD")
    parser.add_argument("--dias", type=int, default=30, help="Si no se indica --desde, últimos N días.")
    parser.add_argument("--clave", default="", help="Claves SIH separadas por coma; vacío = todas.")
    parser.add_argument("--archivo-dir", default=None,
                        help="Carpeta local con {clave}.csv (si la descarga está bloqueada).")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    archivo_dir = Path(args.archivo_dir) if args.archivo_dir else None
    if archivo_dir is not None and not archivo_dir.is_dir():
        raise SystemExit(f"No existe la carpeta {archivo_dir}")

    hasta = date.fromisoformat(args.hasta) if args.hasta else date.today()
    desde_solicitado = (
        date.fromisoformat(args.desde)
        if args.desde
        else hasta - timedelta(days=max(1, args.dias) - 1)
    )
    if desde_solicitado < DESDE_MINIMO:
        print(
            f"Aviso: la ventana mínima es {DESDE_MINIMO}; "
            f"se usa {DESDE_MINIMO} en lugar de {desde_solicitado}."
        )
    desde = clamp_desde(desde_solicitado)
    if desde > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    engine = get_engine()
    fuente_id = get_fuente_id(engine, "SIH_CSV_DIARIO")
    variable_map = get_variable_map(engine)

    sql = "SELECT estacion_id, clave_sih FROM {{schema}}.estacion WHERE clave_sih IS NOT NULL"
    params = {}
    claves = [c.strip() for c in args.clave.split(",") if c.strip()]
    if claves:
        placeholders = ",".join(f":c{i}" for i in range(len(claves)))
        sql += f" AND clave_sih IN ({placeholders})"
        params = {f"c{i}": c for i, c in enumerate(claves)}
    sql += " ORDER BY clave_sih"
    estaciones = read_sql(engine, sql, params)
    if args.limit:
        estaciones = estaciones.head(args.limit)

    if estaciones.empty:
        print("No hay estaciones con clave_sih. Ejecuta primero el enlace SIH.")
        return 1

    print(f"Estaciones: {len(estaciones)} | rango: {desde} -> {hasta}")

    resultados = []
    errores = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                fetch_and_parse, row.clave_sih, desde, hasta, args.timeout, archivo_dir
            ): row
            for row in estaciones.itertuples(index=False)
        }
        for future in as_completed(futures):
            clave, rows, error = future.result()
            if error:
                errores += 1
                print(f"  ! {clave}: {error}")
            resultados.append((clave, rows))

    total = 0
    with log_carga(engine, "load_clima_sih", "SIH_CSV_DIARIO") as info:
        for clave, rows in resultados:
            if not rows:
                continue
            estacion_id = int(
                estaciones.loc[estaciones["clave_sih"] == clave, "estacion_id"].iloc[0]
            )
            values = [
                (estacion_id, variable_map[v], f, val, fuente_id, "OK")
                for (v, f, val) in rows
                if v in variable_map
            ]
            if not values:
                continue
            total += len(values)
            if args.dry_run:
                continue
            with engine.begin() as conn:
                conn.exec_driver_sql(render_sql(SQL_DELETE), (estacion_id, fuente_id, desde, hasta))
            insert_rows(engine, SQL_INSERT, values)
        info["filas"] = total

    print(f"Filas diarias {'(simulación) ' if args.dry_run else ''}procesadas: {total:,}")
    if total == 0 and errores > 0:
        print(f"No se cargaron datos: {errores} estación(es) fallaron.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
