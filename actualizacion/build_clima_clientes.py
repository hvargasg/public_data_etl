"""Clima derivado para las ubicaciones de clientes (`dbo.Clientes`).

El proceso tiene tres fases, todas idempotentes:

1. Sincroniza las celdas de ~1 km (`cliente_ubicacion`) y el enlace
   cliente-domicilio -> celda (`cliente_ubicacion_map`) desde `dbo.Clientes`.
2. Construye el puente `cliente_estacion` con las k estaciones OPERANDO más
   cercanas a cada celda, su distancia, diferencia de altitud y peso IDW.
3. Deriva `clima_cliente_mensual` (NEAREST e IDW) desde
   `vw_clima_mensual_vigente`, igual que el clima de sitios.

No se guarda clima diario por cliente: para eso existen las vistas
`vw_clima_cliente_diario` y `vw_clima_cliente_diario_cercano`. Las decisiones
completas están en `docs/clima_clientes.md`.

Uso:
    python -m actualizacion.build_clima_clientes
    python -m actualizacion.build_clima_clientes --todo
    python -m actualizacion.build_clima_clientes --desde 2025-01 --hasta 2025-12
    python -m actualizacion.build_clima_clientes --recalcular-puente
    python -m actualizacion.build_clima_clientes --sin-mensual --limite 200
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from comun.constants import DESDE_MINIMO, clamp_desde
from comun.db import exec_sql_file, get_engine, log_carga, render_sql

SQL_DDL = Path(__file__).resolve().parent / "sql" / "11_clima_clientes.sql"

# Misma ventana que usa load_claves_geo para considerar una coordenada válida.
LAT_MIN, LAT_MAX = 14.0, 33.0
LON_MIN, LON_MAX = -118.0, -86.0

# 2 decimales ~ 1.1 km en México. Ver docs/clima_clientes.md.
DECIMALES_CELDA = 2

# Token que reemplaza render_sql(). Se inserta como valor en las f-strings.
S = "{{schema}}"

CELDAS_BASE = """
;WITH celdas AS (
    SELECT
        CAST(ROUND(CAST(Lat AS DECIMAL(9, 6)), {dec}) AS DECIMAL(9, 6)) AS lat,
        CAST(ROUND(CAST(Lon AS DECIMAL(9, 6)), {dec}) AS DECIMAL(9, 6)) AS lon,
        MIN(cvegeo) AS cvegeo,
        COALESCE(LEFT(MIN(cvegeo), 2), MIN(cve_ent)) AS cve_ent
    FROM dbo.Clientes
    WHERE Direccion_id IS NOT NULL
      AND Lat IS NOT NULL AND Lon IS NOT NULL
      AND Lat BETWEEN {lat_min} AND {lat_max}
      AND Lon BETWEEN {lon_min} AND {lon_max}
    GROUP BY
        CAST(ROUND(CAST(Lat AS DECIMAL(9, 6)), {dec}) AS DECIMAL(9, 6)),
        CAST(ROUND(CAST(Lon AS DECIMAL(9, 6)), {dec}) AS DECIMAL(9, 6))
)
""".format(
    dec=DECIMALES_CELDA,
    lat_min=LAT_MIN,
    lat_max=LAT_MAX,
    lon_min=LON_MIN,
    lon_max=LON_MAX,
)

SQL_INSERT_CELDAS = CELDAS_BASE + f"""
INSERT INTO {S}.cliente_ubicacion (lat, lon, geom, cve_ent, cvegeo)
SELECT c.lat, c.lon, geography::Point(c.lat, c.lon, 4326), c.cve_ent, c.cvegeo
FROM celdas c
WHERE NOT EXISTS (
    SELECT 1 FROM {S}.cliente_ubicacion u
    WHERE u.lat = c.lat AND u.lon = c.lon
);
"""

SQL_ACTUALIZA_CELDAS = CELDAS_BASE + f"""
UPDATE u
SET cvegeo = COALESCE(u.cvegeo, c.cvegeo),
    cve_ent = COALESCE(LEFT(COALESCE(u.cvegeo, c.cvegeo), 2),
                       COALESCE(u.cve_ent, c.cve_ent))
FROM {S}.cliente_ubicacion u
JOIN celdas c ON c.lat = u.lat AND c.lon = u.lon
WHERE u.cve_ent IS NULL OR u.cvegeo IS NULL;
"""

SQL_BORRA_MAPA_VIEJO = f"""
;WITH validos AS (
    SELECT Cliente_id, Direccion_id
    FROM dbo.Clientes
    WHERE Direccion_id IS NOT NULL
      AND Lat IS NOT NULL AND Lon IS NOT NULL
      AND Lat BETWEEN {LAT_MIN} AND {LAT_MAX}
      AND Lon BETWEEN {LON_MIN} AND {LON_MAX}
)
DELETE m
FROM {S}.cliente_ubicacion_map m
WHERE NOT EXISTS (
    SELECT 1 FROM validos v
    WHERE v.Cliente_id = m.Cliente_id AND v.Direccion_id = m.Direccion_id
);
"""

SQL_ACTUALIZA_MAPA = f"""
;WITH celdas AS (
    SELECT
        Cliente_id, Direccion_id,
        CAST(ROUND(CAST(Lat AS DECIMAL(9, 6)), {DECIMALES_CELDA}) AS DECIMAL(9, 6)) AS lat,
        CAST(ROUND(CAST(Lon AS DECIMAL(9, 6)), {DECIMALES_CELDA}) AS DECIMAL(9, 6)) AS lon
    FROM dbo.Clientes
    WHERE Direccion_id IS NOT NULL
      AND Lat IS NOT NULL AND Lon IS NOT NULL
      AND Lat BETWEEN {LAT_MIN} AND {LAT_MAX}
      AND Lon BETWEEN {LON_MIN} AND {LON_MAX}
)
MERGE {S}.cliente_ubicacion_map AS t
USING (
    SELECT c.Cliente_id, c.Direccion_id, u.ubicacion_id
    FROM celdas c
    JOIN {S}.cliente_ubicacion u
      ON u.lat = c.lat AND u.lon = c.lon
) AS s
ON t.Cliente_id = s.Cliente_id AND t.Direccion_id = s.Direccion_id
WHEN MATCHED AND t.ubicacion_id <> s.ubicacion_id THEN
    UPDATE SET ubicacion_id = s.ubicacion_id, fecha_carga = SYSUTCDATETIME()
WHEN NOT MATCHED THEN
    INSERT (Cliente_id, Direccion_id, ubicacion_id)
    VALUES (s.Cliente_id, s.Direccion_id, s.ubicacion_id);
"""

SQL_PUENTE_DELETE = f"DELETE FROM {S}.cliente_estacion;"

def sql_puente_insert(limite: int | None) -> str:
    """SQL del puente. `limite` solo se usa en pruebas."""
    top = f"TOP ({limite})" if limite else ""
    orden = "ORDER BY u.ubicacion_id" if limite else ""
    return f"""
;WITH base AS (
    SELECT u.ubicacion_id, x.estacion_id, x.ranking, x.distancia_km, x.d_altitud_m,
           CASE WHEN x.distancia_km < 0.001 THEN 1.0
                ELSE 1.0 / (x.distancia_km * x.distancia_km) END AS peso
    FROM (
        SELECT {top} u.ubicacion_id, u.geom, u.altitud_m
        FROM {S}.cliente_ubicacion u
        WHERE NOT EXISTS (
            SELECT 1 FROM {S}.cliente_estacion ce
            WHERE ce.ubicacion_id = u.ubicacion_id
        )
        {orden}
    ) u
    CROSS APPLY (
        SELECT TOP (?)
               e.estacion_id,
               ROW_NUMBER() OVER (ORDER BY u.geom.STDistance(e.geom)) AS ranking,
               u.geom.STDistance(e.geom) / 1000.0 AS distancia_km,
               CASE WHEN u.altitud_m IS NULL THEN NULL
                    ELSE e.altitud_m - u.altitud_m END AS d_altitud_m
        FROM {S}.estacion e
        WHERE e.situacion = 'OPERANDO'
        ORDER BY u.geom.STDistance(e.geom)
    ) x
)
INSERT INTO {S}.cliente_estacion
    (ubicacion_id, estacion_id, ranking, distancia_km, d_altitud_m, peso_idw)
SELECT ubicacion_id, estacion_id, ranking,
       CAST(distancia_km AS DECIMAL(6, 2)),
       CAST(d_altitud_m AS DECIMAL(6, 1)),
       CAST(peso / SUM(peso) OVER (PARTITION BY ubicacion_id) AS DECIMAL(10, 6))
FROM base;
"""

SQL_PUENTE_ANTIGUO = f"""
SELECT CASE
           WHEN COUNT(*) = 0 THEN 1
           WHEN MAX(fecha_carga) IS NULL THEN 1
           WHEN DATEDIFF(day, MAX(fecha_carga), SYSUTCDATETIME()) >= ? THEN 1
           ELSE 0
       END
FROM {S}.cliente_estacion;
"""

SQL_BORRA_MENSUAL = f"""
DELETE FROM {S}.clima_cliente_mensual
WHERE metodo = ?
  AND DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ?;
"""

SQL_MENSUAL_NEAREST = f"""
INSERT INTO {S}.clima_cliente_mensual
    (ubicacion_id, variable_id, anio, mes, valor, metodo, n_estaciones)
SELECT ce.ubicacion_id, m.variable_id, m.anio, m.mes, m.valor,
       'NEAREST', 1
FROM {S}.cliente_estacion ce
JOIN {S}.vw_clima_mensual_vigente m ON m.estacion_id = ce.estacion_id
WHERE ce.ranking = 1
  AND m.valor IS NOT NULL
  AND DATEFROMPARTS(m.anio, m.mes, 1) BETWEEN ? AND ?
  AND (? = 0 OR m.completo IS NULL OR m.completo = 1);
"""

SQL_MENSUAL_IDW = f"""
INSERT INTO {S}.clima_cliente_mensual
    (ubicacion_id, variable_id, anio, mes, valor, metodo, n_estaciones)
SELECT ce.ubicacion_id, m.variable_id, m.anio, m.mes,
       SUM(m.valor * ce.peso_idw) / NULLIF(SUM(ce.peso_idw), 0),
       'IDW', COUNT(DISTINCT ce.estacion_id)
FROM {S}.cliente_estacion ce
JOIN {S}.vw_clima_mensual_vigente m ON m.estacion_id = ce.estacion_id
WHERE ce.peso_idw IS NOT NULL
  AND m.valor IS NOT NULL
  AND DATEFROMPARTS(m.anio, m.mes, 1) BETWEEN ? AND ?
  AND (? = 0 OR m.completo IS NULL OR m.completo = 1)
GROUP BY ce.ubicacion_id, m.variable_id, m.anio, m.mes;
"""


def month_start(value: str | None, default: date) -> date:
    if not value:
        return default
    parts = value.split("-")
    return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)


def rango_meses(
    desde: str | None, hasta: str | None, todo: bool, meses: int
) -> tuple[date, date]:
    hoy = date.today()
    fin = month_start(hasta, date(hoy.year, hoy.month, 1))

    if todo:
        inicio = DESDE_MINIMO
    elif desde:
        inicio = clamp_desde(month_start(desde, DESDE_MINIMO))
    else:
        # Últimos N meses, incluido el actual.
        indice = hoy.year * 12 + (hoy.month - 1) - (meses - 1)
        inicio = clamp_desde(date(indice // 12, indice % 12 + 1, 1))

    if inicio > fin:
        raise SystemExit("--desde no puede ser mayor que --hasta")
    return inicio, fin


def sincronizar_ubicaciones(engine) -> int:
    """Inserta celdas nuevas y actualiza el mapa cliente -> celda."""
    with engine.begin() as conn:
        nuevas = conn.exec_driver_sql(render_sql(SQL_INSERT_CELDAS)).rowcount
        conn.exec_driver_sql(render_sql(SQL_ACTUALIZA_CELDAS))
        conn.exec_driver_sql(render_sql(SQL_BORRA_MAPA_VIEJO))
        conn.exec_driver_sql(render_sql(SQL_ACTUALIZA_MAPA))
    return max(nuevas, 0)


def construir_puente(
    engine, k: int, limite: int | None, recalcular: bool, dias: int
) -> int:
    """Construye o refresca el puente celda-estación."""
    with engine.begin() as conn:
        antiguo = int(
            conn.exec_driver_sql(render_sql(SQL_PUENTE_ANTIGUO), (dias,)).scalar() or 0
        )
        if recalcular or antiguo:
            conn.exec_driver_sql(render_sql(SQL_PUENTE_DELETE))

        sql = sql_puente_insert(limite)
        conn.exec_driver_sql(render_sql(sql), (k,))
        return int(
            conn.exec_driver_sql(
                render_sql(f"SELECT COUNT(*) FROM {S}.cliente_estacion")
            ).scalar_one()
        )


def construir_mensual(
    engine,
    desde: date,
    hasta: date,
    metodos: list[str],
    solo_completos: bool,
) -> int:
    """Recalcula el clima mensual derivado para el rango y métodos pedidos."""
    flag = 1 if solo_completos else 0
    total = 0
    with engine.begin() as conn:
        for metodo in metodos:
            conn.exec_driver_sql(render_sql(SQL_BORRA_MENSUAL), (metodo, desde, hasta))
            sql = SQL_MENSUAL_NEAREST if metodo == "NEAREST" else SQL_MENSUAL_IDW
            conn.exec_driver_sql(render_sql(sql), (desde, hasta, flag))
            total += int(
                conn.exec_driver_sql(
                    render_sql(
                        f"SELECT COUNT(*) FROM {S}.clima_cliente_mensual "
                        "WHERE metodo = ? "
                        "AND DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ?"
                    ),
                    (metodo, desde, hasta),
                ).scalar_one()
            )
    return total


def resumen(engine) -> dict:
    sql = render_sql(
        f"""
        SELECT
            (SELECT COUNT(*) FROM {S}.cliente_ubicacion) AS celdas,
            (SELECT COUNT(*) FROM {S}.cliente_ubicacion_map) AS domicilios,
            (SELECT COUNT(*) FROM {S}.cliente_estacion) AS puente,
            (SELECT COUNT(DISTINCT ubicacion_id) FROM {S}.cliente_estacion) AS celdas_con_puente,
            (SELECT COUNT(*) FROM {S}.clima_cliente_mensual) AS mensual
        """
    )
    with engine.connect() as conn:
        return dict(conn.exec_driver_sql(sql).mappings().one())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deriva clima mensual para las ubicaciones de clientes."
    )
    parser.add_argument("--k", type=int, default=5, help="Estaciones vecinas por celda (1-20).")
    parser.add_argument(
        "--dias-puente",
        type=int,
        default=30,
        help="Refresca el puente si tiene más de N días (default: 30).",
    )
    parser.add_argument(
        "--recalcular-puente",
        action="store_true",
        help="Reconstruye el puente completo, aunque no esté viejo.",
    )
    parser.add_argument("--sin-puente", action="store_true", help="No tocar el puente.")
    parser.add_argument("--sin-mensual", action="store_true", help="No recalcular el mensual.")
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Solo N celdas nuevas del puente (pruebas).",
    )
    parser.add_argument("--desde", default=None, help="YYYY o YYYY-MM.")
    parser.add_argument("--hasta", default=None, help="YYYY o YYYY-MM.")
    parser.add_argument("--todo", action="store_true", help="Desde 2023-01 hasta el mes actual.")
    parser.add_argument(
        "--meses",
        type=int,
        default=2,
        help="Meses hacia atrás si no se indica rango (default: 2).",
    )
    parser.add_argument("--metodos", default="NEAREST,IDW", help="NEAREST, IDW o ambos.")
    parser.add_argument(
        "--solo-completos",
        action="store_true",
        help="Usar solo meses con completo = 1.",
    )
    args = parser.parse_args()

    if not 1 <= args.k <= 20:
        raise SystemExit("--k debe estar entre 1 y 20")
    if args.dias_puente < 0:
        raise SystemExit("--dias-puente no puede ser negativo")
    if args.meses < 1:
        raise SystemExit("--meses debe ser mayor o igual a 1")
    if args.limite is not None and args.limite < 1:
        raise SystemExit("--limite debe ser mayor o igual a 1")

    metodos = [m.strip().upper() for m in args.metodos.split(",") if m.strip()]
    metodos = [m for m in metodos if m in {"NEAREST", "IDW"}]
    if not metodos:
        raise SystemExit("--metodos debe incluir NEAREST y/o IDW")

    desde, hasta = rango_meses(args.desde, args.hasta, args.todo, args.meses)

    engine = get_engine()
    exec_sql_file(engine, SQL_DDL)

    with log_carga(engine, "build_clima_clientes") as info:
        nuevas_celdas = sincronizar_ubicaciones(engine)

        puente = None
        if not args.sin_puente:
            puente = construir_puente(
                engine, args.k, args.limite, args.recalcular_puente, args.dias_puente
            )

        mensual = 0
        if not args.sin_mensual:
            mensual = construir_mensual(
                engine, desde, hasta, metodos, args.solo_completos
            )

        r = resumen(engine)
        info["filas"] = mensual
        info["mensaje"] = (
            f"celdas nuevas {nuevas_celdas}; celdas {r['celdas']}; "
            f"domicilios {r['domicilios']}; puente {r['puente']} "
            f"({r['celdas_con_puente']} celdas); "
            f"mensual {r['mensual']} ({desde:%Y-%m}..{hasta:%Y-%m}, "
            f"{','.join(metodos)})"
        )

    detalle_puente = "" if puente is None else f" (k={args.k})"
    print(
        f"\nClima de clientes\n"
        f"  celdas nuevas   : {nuevas_celdas:,}\n"
        f"  celdas totales  : {r['celdas']:,}\n"
        f"  domicilios      : {r['domicilios']:,}\n"
        f"  puente          : {r['puente']:,} filas en "
        f"{r['celdas_con_puente']:,} celdas{detalle_puente}\n"
        f"  mensual         : {r['mensual']:,} filas "
        f"({desde:%Y-%m}..{hasta:%Y-%m}; {','.join(metodos)})\n"
        f"  filas nuevas    : {mensual:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
