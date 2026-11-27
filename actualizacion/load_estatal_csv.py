"""Carga la serie estatal mensual desde los CSV de la red reducida del SMN.

Reemplaza la descarga y el parsing de PDFs como fuente operativa:

  * descarga los CSV mensuales de TMax, TMed, TMin y Lluv;
  * agrega por entidad federativa (media simple de estaciones);
  * hace *upsert* en `clima_estatal_mensual` con `fuente_id = SMN_RED_CSV`;
  * no escribe archivos: todo se parsea en memoria.

Diferencias con los PDFs estatales (ver `docs/fuentes.md`):
  * temperatura: prácticamente idéntica (±0.3 °C);
  * lluvia: estimación de la red reducida, difiere del PDF oficial ~5–25%.

Los PDFs siguen disponibles con `actualizacion.load_estatal_pdf` como fuente
legacy/opcional. La vista `vw_clima_estatal_vigente` prioriza el CSV y usa el
PDF solo si falta el mes.

Uso:
    python -m actualizacion.load_estatal_csv
    python -m actualizacion.load_estatal_csv --meses 6
    python -m actualizacion.load_estatal_csv --desde 2025-01 --hasta 2025-12
    python -m actualizacion.load_estatal_csv --todo
    python -m actualizacion.load_estatal_csv --dry-run
"""

from __future__ import annotations

import argparse
import csv
import io
import unicodedata
from datetime import date
from pathlib import Path

import requests

from comun.constants import ANIO_MINIMO
from comun.db import (
    exec_sql_file,
    get_engine,
    get_fuente_id,
    get_variable_map,
    log_carga,
    render_sql,
)
from actualizacion.sync_clima_hist import mes_anterior, sincronizar_clima_hist

SQL_DDL = Path(__file__).resolve().parent / "sql" / "12_estatal_csv.sql"

URL_BASE = (
    "https://smn.conagua.gob.mx/tools/RESOURCES/"
    "com_archivo_datos_resumenes"
)

# nombre del archivo CSV -> código de variable
VARIABLES = {
    "TMax": "TMAX",
    "TMed": "TMED",
    "TMin": "TMIN",
    "Lluv": "PREC",
}

# Abreviaturas usadas por la red reducida. La lluvia usa DF en lugar de CDMX.
ABREV_ENTIDAD = {
    "AGS": "01", "BC": "02", "BCS": "03", "CAMP": "04",
    "COAH": "05", "COL": "06", "CHIS": "07", "CHIH": "08",
    "CDMX": "09", "DF": "09", "DGO": "10", "GTO": "11",
    "GRO": "12", "HGO": "13", "JAL": "14", "MEX": "15",
    "MICH": "16", "MOR": "17", "NAY": "18", "NL": "19",
    "OAX": "20", "PUE": "21", "QRO": "22", "QROO": "23",
    "SLP": "24", "SIN": "25", "SON": "26", "TAB": "27",
    "TAMP": "28", "TAMPS": "28", "TLAX": "29", "VER": "30",
    "YUC": "31", "ZAC": "32",
}

# Alias de nombres largos que no coinciden exactamente con INEGI.
ALIAS_ENTIDAD = {
    "COAHUILA": "05",
    "ESTADO DE MEXICO": "15",
    "MEXICO": "15",
    "MICHOACAN": "16",
    "VERACRUZ": "30",
    "DISTRITO FEDERAL": "09",
    "CDMX": "09",
}


def normalizar(texto: str) -> str:
    """Mayúsculas, sin acentos, con espacios simples."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return " ".join(sin_acentos.upper().split())


def mapa_entidades(engine) -> dict[str, str]:
    """Abreviatura o nombre largo -> cve_ent."""
    sql = render_sql("SELECT cve_ent, nom_ent FROM {{schema}}.entidad")
    with engine.connect() as conn:
        filas = conn.exec_driver_sql(sql).mappings().all()
    mapa = {normalizar(f["nom_ent"]): f["cve_ent"] for f in filas}
    mapa.update({normalizar(k): v for k, v in ABREV_ENTIDAD.items()})
    mapa.update({normalizar(k): v for k, v in ALIAS_ENTIDAD.items()})
    return mapa


def month_start(value: str | None, default: date) -> date:
    if not value:
        return default
    parts = value.split("-")
    return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)


def rango_meses(
    desde: str | None, hasta: str | None, todo: bool, meses: int
) -> tuple[date, date]:
    hoy = date.today()
    # El CSV del mes en curso se publica cuando termina el mes.
    if hoy.month == 1:
        fin_por_defecto = date(hoy.year - 1, 12, 1)
    else:
        fin_por_defecto = date(hoy.year, hoy.month - 1, 1)
    fin = month_start(hasta, fin_por_defecto)

    if todo:
        inicio = date(ANIO_MINIMO, 1, 1)
    elif desde:
        inicio = max(month_start(desde, date(ANIO_MINIMO, 1, 1)),
                     date(ANIO_MINIMO, 1, 1))
    else:
        indice = fin.year * 12 + (fin.month - 1) - (meses - 1)
        inicio = date(indice // 12, indice % 12 + 1, 1)
        inicio = max(inicio, date(ANIO_MINIMO, 1, 1))

    if inicio > fin:
        raise SystemExit("--desde no puede ser mayor que --hasta")
    return inicio, fin


def meses_entre(desde: date, hasta: date) -> list[tuple[int, int]]:
    meses: list[tuple[int, int]] = []
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        meses.append((anio, mes))
        if mes == 12:
            anio, mes = anio + 1, 1
        else:
            mes += 1
    return meses


def descargar(session: requests.Session, anio: int, mes: int, archivo: str) -> str | None:
    url = f"{URL_BASE}/{anio:04d}{mes:02d}010000{archivo}.csv"
    respuesta = session.get(url, timeout=90)
    if respuesta.status_code == 404:
        return None
    respuesta.raise_for_status()
    # Los CSV recientes de temperatura vienen en UTF-8; los históricos y la
    # lluvia vienen en latin-1/cp1252.
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return respuesta.content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("no se pudo decodificar el CSV")


def agregar_por_estado(texto: str, mapa: dict[str, str]) -> dict[str, tuple[float, int]]:
    """Media simple por entidad. Devuelve cve_ent -> (media, n_estaciones)."""
    lector = csv.DictReader(io.StringIO(texto))
    if not lector.fieldnames:
        raise ValueError("CSV sin encabezado")

    campos = {c.strip().upper(): c for c in lector.fieldnames}
    col_edo = campos.get("EDO")
    if not col_edo:
        raise ValueError(f"CSV sin columna EDO: {lector.fieldnames}")

    # La columna de datos es la que no es metadato (TMax/TMed/TMin/ene-25...).
    metadatos = {"LON", "LAT", "CLAVE", "EDO", "EST", "ESTACION"}
    col_valor = next(
        (c for c in lector.fieldnames if c.strip().upper() not in metadatos),
        lector.fieldnames[-1],
    )

    acumulado: dict[str, list[float]] = {}
    for fila in lector:
        edo = (fila.get(col_edo) or "").strip()
        cve = mapa.get(normalizar(edo))
        if not cve:
            continue
        crudo = (fila.get(col_valor) or "").strip()
        if crudo in {"", "-", "N/A", "NA"}:
            continue
        try:
            valor = float(crudo.replace(",", ""))
        except ValueError:
            continue
        acumulado.setdefault(cve, []).append(valor)

    return {
        cve: (sum(valores) / len(valores), len(valores))
        for cve, valores in acumulado.items()
        if valores
    }


def cargar(
    engine,
    filas: list[tuple[str, int, int, int, float, int]],
    pares_ok: set[tuple[int, int, int]],
    fuente_id: int,
) -> int:
    sql_delete = render_sql(
        "DELETE FROM {{schema}}.clima_estatal_mensual "
        "WHERE fuente_id = ? AND anio = ? AND mes = ? AND variable_id = ?"
    )
    sql_insert = render_sql(
        "INSERT INTO {{schema}}.clima_estatal_mensual "
        "(cve_ent, variable_id, anio, mes, valor, fuente_id) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )

    with engine.begin() as conn:
        for anio, mes, variable_id in sorted(pares_ok):
            conn.exec_driver_sql(sql_delete, (fuente_id, anio, mes, variable_id))
        for inicio in range(0, len(filas), 1000):
            conn.exec_driver_sql(sql_insert, filas[inicio : inicio + 1000])
    return len(filas)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carga la serie estatal mensual desde la red reducida (CSV)."
    )
    parser.add_argument("--desde", default=None, help="YYYY o YYYY-MM.")
    parser.add_argument("--hasta", default=None, help="YYYY o YYYY-MM.")
    parser.add_argument("--meses", type=int, default=3,
                        help="Meses hacia atrás si no se indica rango (default: 3).")
    parser.add_argument("--todo", action="store_true",
                        help=f"Desde {ANIO_MINIMO}-01 hasta el mes anterior.")
    parser.add_argument("--auto", action="store_true",
                        help="Carga el mes anterior si falta; si ya está, no hace nada.")
    parser.add_argument("--sin-clima-hist", action="store_true",
                        help="No sincronizar dbo.clima_hist.")
    parser.add_argument("--variables", default=",".join(VARIABLES),
                        help="TMax,TMed,TMin,Lluv (default: todas).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Descarga y agrega, pero no escribe en la base.")
    args = parser.parse_args()

    if args.meses < 1:
        raise SystemExit("--meses debe ser mayor o igual a 1")
    if args.auto and (args.desde or args.hasta or args.todo):
        raise SystemExit("--auto no se combina con --desde/--hasta/--todo")

    variables = [
        v.strip() for v in args.variables.split(",") if v.strip()
    ]
    variables = [v for v in variables if v in VARIABLES]
    if not variables:
        raise SystemExit(f"--variables debe incluir alguna de {tuple(VARIABLES)}")

    if args.auto:
        desde = hasta = mes_anterior()
        if desde < date(ANIO_MINIMO, 1, 1):
            print("El mes anterior está fuera de la ventana del modelo.")
            return 0
        meses = [(desde.year, desde.month)]
    else:
        desde, hasta = rango_meses(args.desde, args.hasta, args.todo, args.meses)
        meses = meses_entre(desde, hasta)

    engine = get_engine()
    exec_sql_file(engine, SQL_DDL)
    variables_id = get_variable_map(engine)
    mapa = mapa_entidades(engine)
    fuente_id = get_fuente_id(engine, "SMN_RED_CSV")

    if args.auto:
        sql_check = render_sql(
            "SELECT COUNT(DISTINCT variable_id) FROM {{schema}}.clima_estatal_mensual "
            "WHERE fuente_id = ? AND anio = ? AND mes = ?"
        )
        with engine.connect() as conn:
            presentes = int(
                conn.exec_driver_sql(
                    sql_check, (fuente_id, desde.year, desde.month)
                ).scalar()
                or 0
            )
        if presentes >= len(variables):
            hist = 0
            if not args.sin_clima_hist:
                hist = sincronizar_clima_hist(engine, desde, hasta)
                if hist:
                    with log_carga(engine, "sync_clima_hist") as sinfo:
                        sinfo["filas"] = hist
                        sinfo["mensaje"] = f"{desde:%Y-%m}; desde --auto"
            print(f"{desde:%Y-%m} ya está cargado; clima_hist: {hist:,} filas")
            return 0

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "public-data-etl/1.0 (+https://github.com/hvargasg/public_data_etl)"}
    )

    filas: list[tuple[str, int, int, int, float, int]] = []
    pares_ok: set[tuple[int, int, int]] = set()
    errores: list[str] = []

    for anio, mes in meses:
        for archivo in variables:
            codigo = VARIABLES[archivo]
            variable_id = variables_id.get(codigo)
            if variable_id is None:
                errores.append(f"{codigo}: no existe en el catálogo")
                continue
            try:
                texto = descargar(session, anio, mes, archivo)
                if texto is None:
                    errores.append(f"{archivo} {anio}-{mes:02d}: sin archivo (404)")
                    continue
                agregado = agregar_por_estado(texto, mapa)
                if not agregado:
                    raise ValueError("sin estaciones válidas")
                for cve, (valor, n) in agregado.items():
                    filas.append((cve, variable_id, anio, mes, round(valor, 3), fuente_id))
                pares_ok.add((anio, mes, variable_id))
                print(
                    f"  {archivo} {anio}-{mes:02d}: "
                    f"{len(agregado)} entidades, {sum(n for _, n in agregado.values())} estaciones"
                )
            except Exception as exc:  # noqa: BLE001
                mensaje = f"{archivo} {anio}-{mes:02d}: {exc}"
                errores.append(mensaje)
                print(f"  [aviso] {mensaje}")

    if not pares_ok:
        if args.auto:
            print("Sin datos nuevos todavía; se reintentará en la próxima corrida.")
            return 0
        raise SystemExit("No se pudo descargar ni agregar ningún CSV")

    auto_incompleto = args.auto and len(pares_ok) < len(meses) * len(variables)

    print(
        f"\nRed reducida {desde:%Y-%m}..{hasta:%Y-%m}: "
        f"{len(filas):,} filas en {len(pares_ok)} pares mes-variable"
    )
    if errores:
        print(f"  avisos: {len(errores)} (ver arriba)")
    if auto_incompleto:
        print("  faltan variables del mes; se reintentará en la próxima corrida")

    if args.dry_run:
        print("  simulación: no se escribe en la base")
        return 0

    with log_carga(engine, "load_estatal_csv", "SMN_RED_CSV") as info:
        info["filas"] = cargar(engine, filas, pares_ok, fuente_id)
        hist = 0
        if not args.sin_clima_hist and not auto_incompleto:
            hist = sincronizar_clima_hist(engine, desde, hasta)
        info["mensaje"] = (
            f"meses {desde:%Y-%m}..{hasta:%Y-%m}; "
            f"variables {','.join(variables)}; pares {len(pares_ok)}; "
            f"filas {info['filas']}; clima_hist {hist}; avisos {len(errores)}"
        )

    print(f"  cargadas {info['filas']:,} filas en clima_estatal_mensual")
    print(f"  clima_hist: {hist:,} filas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
