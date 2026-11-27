"""Carga indicadores demográficos, sociales y económicos por nivel geográfico.

Acepta dos formatos:
  * LARGO: una fila por clave + año + indicador + valor.
  * ANCHO: una fila por clave (+ año) y una columna por indicador.

El indicador se identifica por su `codigo` en el catálogo `indicador`. Si un código
no existe, se reporta y se omite (agrégalo primero al catálogo).

Uso:
    python -m carga_inicial.load_demografia --nivel municipio --archivo censo_mun.csv \
        --anio 2020 --fuente INEGI_CENSO
    python -m carga_inicial.load_demografia --nivel ageb --archivo ageb.xlsx \
        --anio 2020 --fuente INEGI_CENSO --formato ancho
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from comun.db import get_engine, get_fuente_id, log_carga, read_sql, upsert
from comun.utils import normalize, parse_float

NIVELES = {
    "municipio": {
        "tabla": "demografia_municipio",
        "clave": "cvegeo",
        "ancho": 5,
        "geo_tabla": "municipio",
    },
    "localidad": {
        "tabla": "demografia_localidad",
        "clave": "cve_loc",
        "ancho": 9,
        "geo_tabla": "localidad",
    },
    "ageb": {
        "tabla": "demografia_ageb",
        "clave": "cve_ageb",
        "ancho": 13,
        "geo_tabla": "ageb",
    },
}


def pick_column(df: pd.DataFrame, candidates: tuple[str, ...], override: str | None) -> str | None:
    if override:
        if override not in df.columns:
            raise KeyError(f"No existe la columna {override!r}")
        return override
    for candidate in candidates:
        for column in df.columns:
            if normalize(column) == normalize(candidate):
                return column
    return None


def norm_key(value, width: int) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(".0", "") if str(value).strip().endswith(".0") else str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text.zfill(width)


def row_anio(row: dict, col_anio: str | None, default: int | None) -> int | None:
    if not col_anio:
        return default
    value = row.get(col_anio)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    parsed = parse_float(value)
    return int(parsed) if parsed is not None else default


def read_file(path: Path, hoja: str | None, separador: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=hoja or 0)
    return pd.read_csv(path, sep=separador or ",")


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga indicadores demográficos por nivel.")
    parser.add_argument("--nivel", required=True, choices=tuple(NIVELES))
    parser.add_argument("--archivo", required=True)
    parser.add_argument("--anio", type=int, default=None, help="Año si el archivo no lo trae.")
    parser.add_argument("--fuente", required=True, help="Código de la tabla `fuente`.")
    parser.add_argument("--formato", choices=("auto", "largo", "ancho"), default="auto")
    parser.add_argument("--hoja", default=None)
    parser.add_argument("--separador", default=None)
    parser.add_argument("--col-clave", default=None)
    parser.add_argument("--col-anio", default=None)
    parser.add_argument("--col-indicador", default=None)
    parser.add_argument("--col-valor", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    nivel = NIVELES[args.nivel]
    path = Path(args.archivo)
    if not path.exists():
        raise SystemExit(f"No existe {path}")

    df = read_file(path, args.hoja, args.separador)
    if df.empty:
        print("El archivo está vacío.")
        return 1

    col_clave = pick_column(df, (nivel["clave"], "clave", "id", "cvegeo", "cve_loc", "cve_ageb"), args.col_clave)
    if col_clave is None:
        raise SystemExit(f"No encontré la columna de clave. Columnas: {list(df.columns)}")

    col_anio = pick_column(df, ("anio", "año", "year"), args.col_anio)
    col_ind = pick_column(df, ("indicador", "codigo", "variable"), args.col_indicador)
    col_valor = pick_column(df, ("valor", "value", "dato"), args.col_valor)

    formato = args.formato
    if formato == "auto":
        formato = "largo" if (col_ind and col_valor) else "ancho"

    if formato == "largo" and (col_ind is None or col_valor is None):
        raise SystemExit("Formato largo requiere columna de indicador y de valor.")

    engine = get_engine()
    fuente_id = get_fuente_id(engine, args.fuente)

    indicadores = read_sql(
        engine, "SELECT indicador_id, codigo FROM {{schema}}.indicador"
    )
    ind_map = {
        normalize(str(r.codigo)): int(r.indicador_id)
        for r in indicadores.itertuples(index=False)
    }

    geo = read_sql(
        engine, f"SELECT {nivel['clave']} AS clave FROM {{schema}}.{nivel['geo_tabla']}"
    )
    claves_validas = set(geo["clave"].astype(str))

    if formato == "largo":
        registros = []
        faltan_ind, faltan_geo, sin_anio, sin_valor = set(), 0, 0, 0
        for row in df.to_dict("records"):
            clave = norm_key(row.get(col_clave), nivel["ancho"])
            anio = row_anio(row, col_anio, args.anio)
            codigo = normalize(str(row.get(col_ind, "")))
            valor = parse_float(row.get(col_valor))

            if clave is None:
                faltan_geo += 1
                continue
            if anio is None:
                sin_anio += 1
                continue
            if codigo not in ind_map:
                faltan_ind.add(str(row.get(col_ind)))
                continue
            if valor is None:
                sin_valor += 1
                continue
            if clave not in claves_validas:
                faltan_geo += 1
                continue
            registros.append(
                {
                    nivel["clave"]: clave,
                    "anio": anio,
                    "indicador_id": ind_map[codigo],
                    "valor": valor,
                    "fuente_id": fuente_id,
                }
            )
    else:
        if args.anio is None and col_anio is None:
            raise SystemExit("Formato ancho requiere --anio o una columna de año.")

        excluir = {col_clave}
        if col_anio:
            excluir.add(col_anio)
        candidatas = [c for c in df.columns if c not in excluir]
        columnas_ind = [c for c in candidatas if normalize(str(c)) in ind_map]
        ignoradas = [str(c) for c in candidatas if normalize(str(c)) not in ind_map]
        if ignoradas:
            print(f"Columnas ignoradas (no son indicadores registrados): {ignoradas[:20]}")

        registros = []
        faltan_ind, faltan_geo, sin_anio, sin_valor = set(), 0, 0, 0
        for row in df.to_dict("records"):
            clave = norm_key(row.get(col_clave), nivel["ancho"])
            anio = row_anio(row, col_anio, args.anio)
            if clave is None:
                faltan_geo += 1
                continue
            if anio is None:
                sin_anio += 1
                continue
            if clave not in claves_validas:
                faltan_geo += 1
                continue
            for columna in columnas_ind:
                codigo = normalize(str(columna))
                valor = parse_float(row.get(columna))
                if valor is None:
                    sin_valor += 1
                    continue
                registros.append(
                    {
                        nivel["clave"]: clave,
                        "anio": anio,
                        "indicador_id": ind_map[codigo],
                        "valor": valor,
                        "fuente_id": fuente_id,
                    }
                )

    if faltan_ind:
        print(f"Indicadores no registrados en indicador (se omiten): {sorted(faltan_ind)[:20]}")
    if faltan_geo:
        print(f"Filas con clave inexistente o vacía (se omiten): {faltan_geo}")
    if sin_anio:
        print(f"Filas sin año (se omiten): {sin_anio}")
    if sin_valor:
        print(f"Celdas sin valor (se omiten): {sin_valor}")

    if not registros:
        print("No hay registros válidos para cargar.")
        return 1

    out = pd.DataFrame(registros)
    print(f"Registros válidos: {len(out):,} | nivel: {args.nivel} | fuente: {args.fuente}")

    if args.dry_run:
        print("Simulación: no se escribió nada.")
        return 0

    with log_carga(engine, f"load_demografia_{args.nivel}", args.fuente) as info:
        info["filas"] = upsert(
            engine,
            out,
            nivel["tabla"],
            key_cols=[nivel["clave"], "anio", "indicador_id", "fuente_id"],
        )

    print(f"Filas cargadas/actualizadas: {info['filas']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
