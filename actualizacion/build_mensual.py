"""Construye la serie mensual propia (CALCULADO) a partir de clima_diario.

Ventana de carga: desde 2023-01-01 a la fecha. No se calcula el histórico
anterior.

Reglas (ver docs/agregaciones.md):
  * PREC y EVAP se suman.
  * TMAX, TMED y TMIN se promedian.
  * Si una estación/variable/fecha existe en varias fuentes, se usa la de
    mayor prioridad: SIH_CSV_DIARIO > SMN_TXT_DIARIO > cualquier otra.
  * Se guarda dias_con_dato, dias_esperados, completo y fecha_corte.
  * Las filas OFICIAL nunca se tocan; la vista vigente prioriza lo oficial.

Opcionalmente deriva el clima mensual de cada sitio (NEAREST e IDW) desde la
vista vigente hacia clima_sitio_mensual.

Uso:
    python -m actualizacion.build_mensual
    python -m actualizacion.build_mensual --desde 2025-01 --hasta 2025-12
    python -m actualizacion.build_mensual --estacion 123 --sin-sitios
    python -m actualizacion.build_mensual --solo-completos --dry-run
"""

from __future__ import annotations

import argparse
from datetime import date

from comun.constants import DESDE_MINIMO, clamp_desde
from comun.db import get_engine, get_fuente_id, log_carga, read_sql, render_sql

SQL_DELETE_MENSUAL = """
DELETE FROM {{schema}}.clima_mensual
WHERE origen = 'CALCULADO'
  AND fuente_id = ?
  AND DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ?
  AND (? IS NULL OR estacion_id = ?)
"""

SQL_BUILD_MENSUAL = """
;WITH ranked AS (
    SELECT d.estacion_id, d.variable_id, d.fecha, d.valor,
           ROW_NUMBER() OVER (
               PARTITION BY d.estacion_id, d.variable_id, d.fecha
               ORDER BY CASE d.fuente_id
                            WHEN ? THEN 0
                            WHEN ? THEN 1
                            ELSE 9
                        END
           ) AS rn
    FROM {{schema}}.clima_diario d
    WHERE d.valor IS NOT NULL
      AND d.fecha BETWEEN ? AND ?
      AND (? IS NULL OR d.estacion_id = ?)
),
base AS (
    SELECT estacion_id, variable_id, fecha, valor
    FROM ranked
    WHERE rn = 1
),
agg AS (
    SELECT b.estacion_id, b.variable_id,
           YEAR(b.fecha) AS anio, MONTH(b.fecha) AS mes,
           CASE WHEN v.agregacion = 'SUMA'
                THEN SUM(b.valor) ELSE AVG(b.valor) END AS valor,
           COUNT(*) AS dias_con_dato,
           MAX(b.fecha) AS fecha_corte
    FROM base b
    JOIN {{schema}}.variable v ON v.variable_id = b.variable_id
    GROUP BY b.estacion_id, b.variable_id,
             YEAR(b.fecha), MONTH(b.fecha), v.agregacion
)
INSERT INTO {{schema}}.clima_mensual
    (estacion_id, variable_id, anio, mes, valor, origen, estado, fuente_id,
     dias_con_dato, dias_esperados, completo, fecha_corte)
SELECT estacion_id, variable_id, anio, mes, valor, 'CALCULADO', 'PRELIMINAR', ?,
       dias_con_dato,
       DAY(EOMONTH(DATEFROMPARTS(anio, mes, 1))),
       CASE WHEN dias_con_dato >= DAY(EOMONTH(DATEFROMPARTS(anio, mes, 1)))
            THEN 1 ELSE 0 END,
       fecha_corte
FROM agg;
"""

SQL_COUNT_MENSUAL = """
;WITH ranked AS (
    SELECT d.estacion_id, d.variable_id, d.fecha, d.valor,
           ROW_NUMBER() OVER (
               PARTITION BY d.estacion_id, d.variable_id, d.fecha
               ORDER BY CASE d.fuente_id
                            WHEN ? THEN 0
                            WHEN ? THEN 1
                            ELSE 9
                        END
           ) AS rn
    FROM {{schema}}.clima_diario d
    WHERE d.valor IS NOT NULL
      AND d.fecha BETWEEN ? AND ?
      AND (? IS NULL OR d.estacion_id = ?)
)
SELECT COUNT(*) AS total
FROM (
    SELECT estacion_id, variable_id, YEAR(fecha) AS anio, MONTH(fecha) AS mes
    FROM ranked
    WHERE rn = 1
    GROUP BY estacion_id, variable_id, YEAR(fecha), MONTH(fecha)
) x
"""

SQL_DELETE_SITIO = """
DELETE FROM {{schema}}.clima_sitio_mensual
WHERE metodo = ?
  AND DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ?
  AND (? IS NULL OR sitio_id = ?)
"""

SQL_BUILD_SITIO_NEAREST = """
INSERT INTO {{schema}}.clima_sitio_mensual
    (sitio_id, variable_id, anio, mes, valor, metodo, n_estaciones, fecha_calculo)
SELECT se.sitio_id, m.variable_id, m.anio, m.mes, m.valor,
       'NEAREST', 1, SYSUTCDATETIME()
FROM {{schema}}.sitio_estacion se
JOIN {{schema}}.vw_clima_mensual_vigente m ON m.estacion_id = se.estacion_id
WHERE se.ranking = 1
  AND m.valor IS NOT NULL
  AND DATEFROMPARTS(m.anio, m.mes, 1) BETWEEN ? AND ?
  AND (? IS NULL OR se.sitio_id = ?)
  AND (? = 0 OR m.completo IS NULL OR m.completo = 1)
"""

SQL_BUILD_SITIO_IDW = """
INSERT INTO {{schema}}.clima_sitio_mensual
    (sitio_id, variable_id, anio, mes, valor, metodo, n_estaciones, fecha_calculo)
SELECT se.sitio_id, m.variable_id, m.anio, m.mes,
       SUM(m.valor * se.peso_idw) / NULLIF(SUM(se.peso_idw), 0),
       'IDW', COUNT(DISTINCT se.estacion_id), SYSUTCDATETIME()
FROM {{schema}}.sitio_estacion se
JOIN {{schema}}.vw_clima_mensual_vigente m ON m.estacion_id = se.estacion_id
WHERE se.peso_idw IS NOT NULL
  AND m.valor IS NOT NULL
  AND DATEFROMPARTS(m.anio, m.mes, 1) BETWEEN ? AND ?
  AND (? IS NULL OR se.sitio_id = ?)
  AND (? = 0 OR m.completo IS NULL OR m.completo = 1)
GROUP BY se.sitio_id, m.variable_id, m.anio, m.mes
"""


def month_start(value: str | None, default: date) -> date:
    if not value:
        return default
    parts = value.split("-")
    return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)


def month_end(value: str | None, default: date) -> date:
    if not value:
        return default
    parts = value.split("-")
    # Si solo se indica el año, el rango llega hasta diciembre.
    return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 12, 1)


def build_estacion(
    engine,
    fuente_sih: int,
    fuente_smn: int,
    fuente_calc: int,
    desde: date,
    hasta: date,
    estacion_id: int | None,
    dry_run: bool,
) -> int:
    base = (fuente_sih, fuente_smn, desde, hasta, estacion_id, estacion_id)
    if dry_run:
        return int(read_sql(engine, SQL_COUNT_MENSUAL, base).iloc[0, 0])

    with engine.begin() as conn:
        conn.exec_driver_sql(
            render_sql(SQL_DELETE_MENSUAL),
            (fuente_calc, desde, hasta, estacion_id, estacion_id),
        )
        conn.exec_driver_sql(render_sql(SQL_BUILD_MENSUAL), base + (fuente_calc,))
        return int(
            conn.exec_driver_sql(
                render_sql(
                    "SELECT COUNT(*) FROM {{schema}}.clima_mensual "
                    "WHERE origen = 'CALCULADO' AND fuente_id = ? "
                    "AND DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ? "
                    "AND (? IS NULL OR estacion_id = ?)"
                ),
                (fuente_calc, desde, hasta, estacion_id, estacion_id),
            ).scalar_one()
        )


def build_sitios(
    engine,
    desde: date,
    hasta: date,
    sitio_id: int | None,
    metodos: list[str],
    solo_completos: bool,
    dry_run: bool,
) -> int:
    if dry_run:
        return 0

    total = 0
    flag = 1 if solo_completos else 0
    with engine.begin() as conn:
        for metodo in metodos:
            conn.exec_driver_sql(render_sql(SQL_DELETE_SITIO), (metodo, desde, hasta, sitio_id, sitio_id))
            if metodo == "NEAREST":
                sql, params = SQL_BUILD_SITIO_NEAREST, (desde, hasta, sitio_id, sitio_id, flag)
            else:
                sql, params = SQL_BUILD_SITIO_IDW, (desde, hasta, sitio_id, sitio_id, flag)
            conn.exec_driver_sql(render_sql(sql), params)
            total += int(
                conn.exec_driver_sql(
                    render_sql(
                        "SELECT COUNT(*) FROM {{schema}}.clima_sitio_mensual "
                        "WHERE metodo = ? "
                        "AND DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ? "
                        "AND (? IS NULL OR sitio_id = ?)"
                    ),
                    (metodo, desde, hasta, sitio_id, sitio_id),
                ).scalar_one()
            )
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye la serie mensual propia.")
    parser.add_argument("--desde", default=None, help="YYYY, YYYY-MM o YYYY-MM-DD.")
    parser.add_argument("--hasta", default=None, help="YYYY, YYYY-MM o YYYY-MM-DD.")
    parser.add_argument("--estacion", type=int, default=None, help="Solo una estación.")
    parser.add_argument("--sin-sitios", action="store_true", help="No derivar clima de sitios.")
    parser.add_argument("--metodos", default="NEAREST,IDW", help="NEAREST, IDW o ambos.")
    parser.add_argument("--solo-completos", action="store_true",
                        help="Para sitios, usar solo meses completos.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hoy = date.today()
    desde_solicitado = month_start(args.desde, DESDE_MINIMO)
    if desde_solicitado < DESDE_MINIMO:
        print(
            f"Aviso: la ventana mínima es {DESDE_MINIMO}; "
            f"se recalcula desde {DESDE_MINIMO}."
        )
    desde = clamp_desde(desde_solicitado)
    hasta = month_end(args.hasta, date(hoy.year, hoy.month, 1))
    if desde > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    engine = get_engine()
    fuente_calc = get_fuente_id(engine, "CALCULO_PROPIO")
    fuente_sih = get_fuente_id(engine, "SIH_CSV_DIARIO")
    fuente_smn = get_fuente_id(engine, "SMN_TXT_DIARIO")

    # Parámetros compartidos: prioridad SIH > SMN, rango, estación.
    with log_carga(engine, "build_mensual", "CALCULO_PROPIO") as info:
        info["filas"] = build_estacion(
            engine, fuente_sih, fuente_smn, fuente_calc,
            desde, hasta, args.estacion, args.dry_run,
        )

    print(f"Mensual calculado{' (simulación)' if args.dry_run else ''}: {info['filas']:,} filas")

    if not args.sin_sitios and not args.dry_run:
        metodos = [m.strip().upper() for m in args.metodos.split(",") if m.strip()]
        metodos = [m for m in metodos if m in {"NEAREST", "IDW"}]
        if metodos:
            with log_carga(engine, "build_mensual_sitios", "CALCULO_PROPIO") as sinfo:
                sinfo["filas"] = build_sitios(
                    engine, desde, hasta, None, metodos, args.solo_completos, False
                )
            print(f"Clima de sitios ({','.join(metodos)}): {sinfo['filas']:,} filas")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
