"""Descarga y carga los resúmenes estatales mensuales del SMN (PDFs).

Reemplaza el flujo legacy `auto_conagua_download.py`:

  * descarga los PDFs anuales de TMAX, TMED, TMIN y PREC;
  * extrae la tabla estado-mes con `pdfplumber` (sin CSV intermedios);
  * hace *upsert* en `datos_publicos.clima_estatal_mensual` con
    `fuente_id = PDF_ESTATAL`;
  * borra los PDFs temporales al terminar, incluso si hay error.

No modifica `dbo.clima_hist`. La vista `vw_clima_hist_compat` reproduce el
formato ancho para 2023+. Las decisiones y la comparación con la red reducida
están en `docs/fuentes.md`.

Uso:
    python -m actualizacion.load_estatal_pdf
    python -m actualizacion.load_estatal_pdf --todo
    python -m actualizacion.load_estatal_pdf --desde 2024 --hasta 2026
    python -m actualizacion.load_estatal_pdf --variables TMAX,PREC
    python -m actualizacion.load_estatal_pdf --dry-run
"""

from __future__ import annotations

import argparse
import io
import shutil
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

import pdfplumber
import requests

from comun.constants import ANIO_MINIMO
from comun.db import get_engine, get_fuente_id, get_variable_map, log_carga, render_sql

URL_BASE = (
    "https://smn.conagua.gob.mx/tools/DATA/"
    "Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/"
    "Temperatura%20y%20Lluvia"
)

VARIABLES = ("TMAX", "TMED", "TMIN", "PREC")

MESES = {
    "ENE": 1, "ENERO": 1,
    "FEB": 2, "FEBRERO": 2,
    "MAR": 3, "MARZO": 3,
    "ABR": 4, "ABRIL": 4,
    "MAY": 5, "MAYO": 5,
    "JUN": 6, "JUNIO": 6,
    "JUL": 7, "JULIO": 7,
    "AGO": 8, "AGOSTO": 8,
    "SEP": 9, "SEPT": 9, "SEPTIEMBRE": 9,
    "OCT": 10, "OCTUBRE": 10,
    "NOV": 11, "NOVIEMBRE": 11,
    "DIC": 12, "DICIEMBRE": 12,
}

# El PDF usa nombres cortos; INEGI usa el nombre oficial largo.
# La clave y el valor se guardan ya normalizados.
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
    """Mayúsculas, sin acentos, sin puntos y con espacios simples."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    limpio = sin_acentos.upper().replace(".", " ").replace("-", " ")
    return " ".join(limpio.split())


def mapa_entidades(engine) -> dict[str, str]:
    sql = render_sql("SELECT cve_ent, nom_ent FROM {{schema}}.entidad")
    with engine.connect() as conn:
        filas = conn.exec_driver_sql(sql).mappings().all()
    mapa = {normalizar(f["nom_ent"]): f["cve_ent"] for f in filas}
    mapa.update(ALIAS_ENTIDAD)
    return mapa


def descargar(session: requests.Session, variable: str, anio: int) -> bytes:
    url = f"{URL_BASE}/{variable}/{anio}.pdf"
    respuesta = session.get(url, timeout=90)
    respuesta.raise_for_status()
    if not respuesta.content.startswith(b"%PDF"):
        raise ValueError(f"{url} no devolvió un PDF")
    return respuesta.content


def parsear_pdf(
    contenido: bytes, anio: int, variable_id: int, mapa: dict[str, str]
) -> list[tuple[str, int, int, int, float]]:
    """Devuelve filas (cve_ent, variable_id, anio, mes, valor)."""
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        if not pdf.pages:
            raise ValueError("PDF sin páginas")
        tabla = pdf.pages[0].extract_table()

    if not tabla or len(tabla) < 2:
        raise ValueError("no se encontró la tabla estado-mes en la página 1")

    encabezado = [str(c or "").strip() for c in tabla[0]]
    columnas_mes: dict[int, int] = {}
    for indice, celda in enumerate(encabezado):
        mes = MESES.get(normalizar(celda))
        if mes:
            columnas_mes[mes] = indice

    if len(columnas_mes) != 12:
        raise ValueError(
            f"encabezado inesperado ({len(columnas_mes)} meses): {encabezado}"
        )

    filas: list[tuple[str, int, int, int, float]] = []
    for fila in tabla[1:]:
        if not fila:
            continue
        estado = str(fila[0] or "").strip()
        if not estado or normalizar(estado) == "NACIONAL":
            continue

        cve_ent = mapa.get(normalizar(estado))
        if not cve_ent:
            print(f"  [aviso] estado sin mapeo: {estado!r}; se omite")
            continue

        for mes, indice in columnas_mes.items():
            if indice >= len(fila):
                continue
            crudo = fila[indice]
            if crudo is None:
                continue
            texto = str(crudo).strip().replace(",", "")
            if texto in {"", "-", "—", "N/A", "NA"}:
                continue
            try:
                valor = float(texto)
            except ValueError:
                print(f"  [aviso] {estado} {anio}-{mes:02d}: valor no numérico {crudo!r}")
                continue
            filas.append((cve_ent, variable_id, anio, mes, valor))

    return filas


def cargar(
    engine,
    filas: list[tuple[str, int, int, int, float, int]],
    pares_ok: set[tuple[int, int]],
    fuente_id: int,
) -> int:
    """Reemplaza por (año, variable) solo los pares que se parsearon bien."""
    sql_delete = render_sql(
        "DELETE FROM {{schema}}.clima_estatal_mensual "
        "WHERE fuente_id = ? AND anio = ? AND variable_id = ?"
    )
    sql_insert = render_sql(
        "INSERT INTO {{schema}}.clima_estatal_mensual "
        "(cve_ent, variable_id, anio, mes, valor, fuente_id) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )

    with engine.begin() as conn:
        for anio, variable_id in sorted(pares_ok):
            conn.exec_driver_sql(sql_delete, (fuente_id, anio, variable_id))
        for inicio in range(0, len(filas), 1000):
            conn.exec_driver_sql(sql_insert, filas[inicio : inicio + 1000])
    return len(filas)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carga los resúmenes estatales mensuales del SMN desde PDFs."
    )
    parser.add_argument("--desde", type=int, default=None, help="Año inicial (YYYY).")
    parser.add_argument("--hasta", type=int, default=None, help="Año final (YYYY).")
    parser.add_argument("--todo", action="store_true",
                        help=f"Desde {ANIO_MINIMO} hasta el año actual.")
    parser.add_argument("--variables", default=",".join(VARIABLES),
                        help="TMAX,TMED,TMIN,PREC (default: todas).")
    parser.add_argument("--conservar", action="store_true",
                        help="No borrar los PDFs temporales (depuración).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Descarga y parsea, pero no escribe en la base.")
    args = parser.parse_args()

    hoy = date.today()
    hasta = args.hasta or hoy.year
    if args.todo:
        desde = ANIO_MINIMO
    elif args.desde:
        desde = max(args.desde, ANIO_MINIMO)
    else:
        desde = max(hasta - 1, ANIO_MINIMO)
    if desde > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    variables = [
        v.strip().upper() for v in args.variables.split(",") if v.strip()
    ]
    variables = [v for v in variables if v in VARIABLES]
    if not variables:
        raise SystemExit(f"--variables debe incluir alguna de {VARIABLES}")

    engine = get_engine()
    mapa = mapa_entidades(engine)
    variables_id = get_variable_map(engine)
    fuente_id = get_fuente_id(engine, "PDF_ESTATAL")

    anios = list(range(desde, hasta + 1))
    tmpdir = Path(tempfile.mkdtemp(prefix="conagua_estatal_"))

    filas: list[tuple[str, int, int, int, float, int]] = []
    pares_ok: set[tuple[int, int]] = set()
    errores: list[str] = []

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "public-data-etl/1.0 (+https://github.com/hvargasg/public_data_etl)"}
    )

    try:
        for anio in anios:
            for variable in variables:
                variable_id = variables_id.get(variable)
                if variable_id is None:
                    errores.append(f"{variable}: no existe en el catálogo")
                    continue
                try:
                    contenido = descargar(session, variable, anio)
                    # Se guarda para cumplir el flujo legacy y permitir depuración;
                    # el parseo usa los bytes en memoria.
                    (tmpdir / f"{variable}_{anio}.pdf").write_bytes(contenido)
                    nuevas = parsear_pdf(contenido, anio, variable_id, mapa)
                    if not nuevas:
                        raise ValueError("la tabla no produjo filas")
                    filas.extend(
                        (*fila, fuente_id) for fila in nuevas
                    )
                    pares_ok.add((anio, variable_id))
                    print(f"  {variable} {anio}: {len(nuevas):,} filas")
                except Exception as exc:  # noqa: BLE001
                    mensaje = f"{variable} {anio}: {exc}"
                    errores.append(mensaje)
                    print(f"  [aviso] {mensaje}")

        # Deduplicar por si el PDF repite un estado.
        unicas = {
            (f[0], f[1], f[2], f[3]): f for f in filas
        }
        filas = list(unicas.values())

        if not pares_ok:
            raise SystemExit("No se pudo descargar ni parsear ningún PDF")

        print(
            f"\nResúmenes estatales {desde}..{hasta}: "
            f"{len(filas):,} filas en {len(pares_ok)} pares año-variable"
        )
        if errores:
            print(f"  avisos: {len(errores)} (ver arriba)")

        if args.dry_run:
            print("  simulación: no se escribe en la base")
            return 0

        with log_carga(engine, "load_estatal_pdf", "PDF_ESTATAL") as info:
            info["filas"] = cargar(engine, filas, pares_ok, fuente_id)
            info["mensaje"] = (
                f"años {desde}..{hasta}; variables {','.join(variables)}; "
                f"pares {len(pares_ok)}; filas {info['filas']}; "
                f"avisos {len(errores)}"
            )

        print(f"  cargadas {info['filas']:,} filas en clima_estatal_mensual")
        return 0
    finally:
        if args.conservar:
            print(f"  PDFs conservados en {tmpdir}")
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
