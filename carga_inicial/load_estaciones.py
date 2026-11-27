"""Descarga el índice de estaciones del SMN y lo carga en la tabla `estacion`.

Fuente:
    https://smn.conagua.gob.mx/tools/GUI/estaciones-climatologicas/data/estaciones_climatologicas.geojson

Uso:
    python -m carga_inicial.load_estaciones
    python -m carga_inicial.load_estaciones --skip-geo
"""

from __future__ import annotations

import argparse

import requests

from comun.db import get_engine, insert_rows, log_carga, read_sql, render_sql
from comun.utils import parse_date, parse_float

GEOJSON_URL = (
    "https://smn.conagua.gob.mx/tools/GUI/estaciones-climatologicas/"
    "data/estaciones_climatologicas.geojson"
)

SQL_INSERT = """
INSERT INTO {{schema}}.estacion
    (clave_smn, nombre, lat, lon, geom, altitud_m, situacion, tipo,
     organismo, cuenca, inicio, mas_reciente,
     url_mensual, url_diario, url_extremos, version_indice)
VALUES
    (?, ?, ?, ?, geography::Point(?, ?, 4326), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SQL_UPDATE = """
UPDATE {{schema}}.estacion
SET nombre = ?, lat = ?, lon = ?, geom = geography::Point(?, ?, 4326),
    altitud_m = ?, situacion = ?, tipo = ?, organismo = ?, cuenca = ?,
    inicio = ?, mas_reciente = ?, url_mensual = ?, url_diario = ?,
    url_extremos = ?, version_indice = ?, fecha_carga = SYSUTCDATETIME()
WHERE clave_smn = ?
"""

SQL_MUN = """
UPDATE e
SET cvegeo = x.cvegeo, cve_ent = LEFT(x.cvegeo, 2)
FROM {{schema}}.estacion e
CROSS APPLY (
    SELECT TOP (1) m.cvegeo
    FROM {{schema}}.municipio m
    WHERE m.geom.STIntersects(e.geom) = 1
    ORDER BY m.geom.STDistance(e.geom)
) x
WHERE e.cvegeo IS NULL;
"""

SQL_LOC = """
UPDATE e
SET cve_loc = x.cve_loc
FROM {{schema}}.estacion e
CROSS APPLY (
    SELECT TOP (1) l.cve_loc
    FROM {{schema}}.localidad l
    WHERE l.geom.STIntersects(e.geom) = 1
      AND (e.cvegeo IS NULL OR l.cvegeo = e.cvegeo)
    ORDER BY l.geom.STDistance(e.geom)
) x
WHERE e.cve_loc IS NULL;
"""

SQL_AGEB = """
UPDATE e
SET cve_ageb = x.cve_ageb
FROM {{schema}}.estacion e
CROSS APPLY (
    SELECT TOP (1) a.cve_ageb
    FROM {{schema}}.ageb a
    WHERE a.geom.STIntersects(e.geom) = 1
      AND a.cvegeo = e.cvegeo
      AND (a.cve_loc IS NULL OR e.cve_loc IS NULL OR a.cve_loc = e.cve_loc)
    ORDER BY a.geom.STDistance(e.geom)
) x
WHERE e.cve_ageb IS NULL
  AND e.cvegeo IS NOT NULL;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga el índice de estaciones del SMN.")
    parser.add_argument("--url", default=GEOJSON_URL)
    parser.add_argument("--skip-geo", action="store_true", help="No ejecutar el cruce espacial.")
    args = parser.parse_args()

    print(f"Descargando {args.url} ...")
    response = requests.get(args.url, timeout=180)
    response.raise_for_status()
    data = response.json()

    features = data.get("features", [])
    version = str(data.get("generatedAt", "")).strip() or None
    print(f"Estaciones en el índice: {len(features)} | versión: {version}")

    engine = get_engine()
    existentes = set(
        read_sql(engine, "SELECT clave_smn FROM {{schema}}.estacion WHERE clave_smn IS NOT NULL")["clave_smn"]
    )

    nuevos, actualizados = [], []
    for feature in features:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        clave = str(props.get("clave") or "").strip() or None
        if not clave:
            continue

        comunes = (
            props.get("nombre") or "",
            lat,
            lon,
            lat,
            lon,
            parse_float(props.get("altitud")),
            props.get("situacion"),
            props.get("tipo"),
            props.get("organismo"),
            props.get("cuenca"),
            parse_date(props.get("inicio")),
            parse_date(props.get("mas_reciente")),
            props.get("mensuales"),
            props.get("diarios"),
            props.get("extremos"),
            version,
        )
        if clave in existentes:
            actualizados.append(comunes + (clave,))
        else:
            nuevos.append((clave,) + comunes)

    with log_carga(engine, "load_estaciones", "SMN_TXT_MENSUAL") as info:
        info["filas"] += insert_rows(engine, SQL_INSERT, nuevos)
        info["filas"] += insert_rows(engine, SQL_UPDATE, actualizados)

    if not args.skip_geo:
        print("Cruzando estaciones con municipio / localidad / AGEB ...")
        with engine.begin() as conn:
            conn.exec_driver_sql(render_sql(SQL_MUN))
            conn.exec_driver_sql(render_sql(SQL_LOC))
            conn.exec_driver_sql(render_sql(SQL_AGEB))

    print(f"Insertadas: {len(nuevos)} | actualizadas: {len(actualizados)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
