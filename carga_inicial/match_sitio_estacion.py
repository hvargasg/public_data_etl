"""Calcula las k estaciones más cercanas a cada sitio y guarda el puente.

Genera `sitio_estacion` con ranking, distancia, diferencia de altitud
y peso IDW normalizado (1/d^2). Reconstruye la tabla completa en cada corrida.

Uso:
    python -m carga_inicial.match_sitio_estacion
    python -m carga_inicial.match_sitio_estacion --k 3 --solo-operando
"""

from __future__ import annotations

import argparse

from comun.db import get_engine, log_carga, render_sql

SQL = """
;WITH base AS (
    SELECT s.sitio_id,
           x.estacion_id,
           x.ranking,
           x.distancia_km,
           x.d_altitud_m,
           CASE WHEN x.distancia_km < 0.001 THEN 1.0
                ELSE 1.0 / (x.distancia_km * x.distancia_km) END AS peso
    FROM {{schema}}.sitio s
    CROSS APPLY (
        SELECT TOP (?)
               e.estacion_id,
               ROW_NUMBER() OVER (ORDER BY s.geom.STDistance(e.geom)) AS ranking,
               s.geom.STDistance(e.geom) / 1000.0 AS distancia_km,
               e.altitud_m - s.altitud_m AS d_altitud_m
        FROM {{schema}}.estacion e
        WHERE (? = 0 OR e.situacion = 'OPERANDO')
        ORDER BY s.geom.STDistance(e.geom)
    ) x
)
INSERT INTO {{schema}}.sitio_estacion
    (sitio_id, estacion_id, ranking, distancia_km, d_altitud_m, peso_idw, metodo)
SELECT sitio_id, estacion_id, ranking, distancia_km, d_altitud_m,
       peso / SUM(peso) OVER (PARTITION BY sitio_id), 'NEAREST'
FROM base;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Empareja sitios con estaciones cercanas.")
    parser.add_argument("--k", type=int, default=5, help="Número de estaciones por sitio (1-20).")
    parser.add_argument("--solo-operando", action="store_true", help="Solo estaciones OPERANDO.")
    parser.add_argument("--append", action="store_true", help="No borrar el puente antes de insertar.")
    args = parser.parse_args()

    if not 1 <= args.k <= 20:
        raise SystemExit("--k debe estar entre 1 y 20")

    engine = get_engine()
    with log_carga(engine, "match_sitio_estacion") as info:
        with engine.begin() as conn:
            if not args.append:
                conn.exec_driver_sql(render_sql("DELETE FROM {{schema}}.sitio_estacion;"))
            conn.exec_driver_sql(render_sql(SQL), (args.k, 1 if args.solo_operando else 0))
            info["filas"] = conn.exec_driver_sql(
                render_sql("SELECT COUNT(*) FROM {{schema}}.sitio_estacion")
            ).scalar_one()

    print(f"Puente sitio-estación reconstruido (k={args.k}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
