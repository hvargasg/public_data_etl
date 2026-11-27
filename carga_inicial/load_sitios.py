"""Carga los sitios de interés (puntos) y los cruza con la geografía INEGI.

Archivo de entrada: CSV o Excel con columnas id, lat, lon y, opcionalmente,
nombre y altitud. Los nombres de columna se detectan sin distinguir mayúsculas
ni acentos; también se pueden indicar explícitamente.

Uso:
    python -m carga_inicial.load_sitios --archivo sitios.csv
    python -m carga_inicial.load_sitios --archivo sitios.xlsx --hoja Hoja1
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from comun.db import get_engine, insert_rows, log_carga, read_sql, render_sql
from comun.utils import normalize, parse_float

SQL_INSERT = """
INSERT INTO {{schema}}.sitio (codigo_sitio, nombre, lat, lon, geom, altitud_m)
VALUES (?, ?, ?, ?, geography::Point(?, ?, 4326), ?)
"""

SQL_UPDATE = """
UPDATE {{schema}}.sitio
SET nombre = ?, lat = ?, lon = ?, geom = geography::Point(?, ?, 4326),
    altitud_m = ?, fecha_actualizacion = SYSUTCDATETIME()
WHERE codigo_sitio = ?
"""

SQL_MUN = """
UPDATE s
SET cvegeo = x.cvegeo, cve_ent = LEFT(x.cvegeo, 2),
    metodo_asignacion = COALESCE(s.metodo_asignacion, 'within')
FROM {{schema}}.sitio s
CROSS APPLY (
    SELECT TOP (1) m.cvegeo
    FROM {{schema}}.municipio m
    WHERE m.geom.STIntersects(s.geom) = 1
    ORDER BY m.geom.STDistance(s.geom)
) x
WHERE s.cvegeo IS NULL;
"""

SQL_MUN_NEAR = """
UPDATE s
SET cvegeo = x.cvegeo, cve_ent = LEFT(x.cvegeo, 2), metodo_asignacion = 'nearest'
FROM {{schema}}.sitio s
CROSS APPLY (
    SELECT TOP (1) m.cvegeo
    FROM {{schema}}.municipio m
    WHERE s.geom.STDistance(m.geom) <= 5000
    ORDER BY s.geom.STDistance(m.geom)
) x
WHERE s.cvegeo IS NULL;
"""

SQL_LOC = """
UPDATE s
SET cve_loc = x.cve_loc
FROM {{schema}}.sitio s
CROSS APPLY (
    SELECT TOP (1) l.cve_loc
    FROM {{schema}}.localidad l
    WHERE l.geom.STIntersects(s.geom) = 1
      AND (s.cvegeo IS NULL OR l.cvegeo = s.cvegeo)
    ORDER BY l.geom.STDistance(s.geom)
) x
WHERE s.cve_loc IS NULL;
"""

SQL_AGEB = """
UPDATE s
SET cve_ageb = x.cve_ageb
FROM {{schema}}.sitio s
CROSS APPLY (
    SELECT TOP (1) a.cve_ageb
    FROM {{schema}}.ageb a
    WHERE a.geom.STIntersects(s.geom) = 1
      AND a.cvegeo = s.cvegeo
      AND (a.cve_loc IS NULL OR s.cve_loc IS NULL OR a.cve_loc = s.cve_loc)
    ORDER BY a.geom.STDistance(s.geom)
) x
WHERE s.cve_ageb IS NULL
  AND s.cvegeo IS NOT NULL;
"""

SQL_FLAGS = """
UPDATE {{schema}}.sitio
SET sin_localidad = CASE WHEN cve_loc IS NULL THEN 1 ELSE 0 END;

UPDATE {{schema}}.sitio
SET en_limite = 0;

UPDATE s
SET en_limite = 1
FROM {{schema}}.sitio s
WHERE (
    SELECT COUNT(*)
    FROM {{schema}}.municipio m
    WHERE m.geom.STIntersects(s.geom) = 1
) > 1;
"""


def pick_column(df: pd.DataFrame, candidates: tuple[str, ...], override: str | None) -> str:
    if override:
        if override not in df.columns:
            raise KeyError(f"No existe la columna {override!r}")
        return override
    for candidate in candidates:
        for column in df.columns:
            if normalize(column) == normalize(candidate):
                return column
    raise KeyError(f"No encontré columna {candidates}; columnas disponibles: {list(df.columns)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga sitios de interés y los homologa.")
    parser.add_argument("--archivo", required=True)
    parser.add_argument("--hoja", default=None)
    parser.add_argument("--col-id", default=None)
    parser.add_argument("--col-lat", default=None)
    parser.add_argument("--col-lon", default=None)
    parser.add_argument("--col-nombre", default=None)
    parser.add_argument("--col-altitud", default=None)
    args = parser.parse_args()

    path = Path(args.archivo)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, sheet_name=args.hoja or 0)
    else:
        df = pd.read_csv(path)

    col_id = pick_column(df, ("codigo_sitio", "id", "clave", "sitio"), args.col_id)
    col_lat = pick_column(df, ("lat", "latitud"), args.col_lat)
    col_lon = pick_column(df, ("lon", "lng", "longitud"), args.col_lon)
    col_nombre = pick_column(df, ("nombre", "sitio_nombre"), args.col_nombre) if (
        args.col_nombre or any(normalize(c) in {"nombre", "sitio_nombre"} for c in df.columns)
    ) else None
    col_alt = pick_column(df, ("altitud", "altitud_m", "elevacion"), args.col_altitud) if (
        args.col_altitud or any(normalize(c) in {"altitud", "altitudm", "elevacion"} for c in df.columns)
    ) else None

    engine = get_engine()
    existentes = set(
        read_sql(engine, "SELECT codigo_sitio FROM {{schema}}.sitio")["codigo_sitio"]
    )

    nuevos, actualizados = [], []
    for data in df.to_dict("records"):
        codigo = str(data[col_id]).strip()
        if not codigo or codigo.lower() == "nan":
            continue
        lat = parse_float(data[col_lat])
        lon = parse_float(data[col_lon])
        if lat is None or lon is None:
            continue
        nombre = str(data[col_nombre]).strip() if col_nombre and pd.notna(data[col_nombre]) else None
        altitud = parse_float(data[col_alt]) if col_alt else None

        if codigo in existentes:
            actualizados.append((nombre, lat, lon, lat, lon, altitud, codigo))
        else:
            nuevos.append((codigo, nombre, lat, lon, lat, lon, altitud))

    with log_carga(engine, "load_sitios") as info:
        info["filas"] += insert_rows(engine, SQL_INSERT, nuevos)
        info["filas"] += insert_rows(engine, SQL_UPDATE, actualizados)

    print("Cruzando sitios con municipio / localidad / AGEB ...")
    with engine.begin() as conn:
        conn.exec_driver_sql(render_sql(SQL_MUN))
        conn.exec_driver_sql(render_sql(SQL_MUN_NEAR))
        conn.exec_driver_sql(render_sql(SQL_LOC))
        conn.exec_driver_sql(render_sql(SQL_AGEB))
        conn.exec_driver_sql(render_sql(SQL_FLAGS))

    print(f"Insertados: {len(nuevos)} | actualizados: {len(actualizados)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
