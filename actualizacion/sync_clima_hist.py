"""Sincroniza la serie estatal mensual con `dbo.clima_hist` de forma incremental.

Regla por defecto:

- Toma el último mes que ya existe en `dbo.clima_hist`.
- Solo agrega los meses completos **posteriores** a ese último mes.
- Si el último mes está incompleto (menos de 32 entidades), lo completa.
- **No reescribe** los meses anteriores de 2023+ en cada corrida.

`clima_hist` es la tabla legacy en formato ancho. La serie se toma de
`vw_clima_estatal_vigente` (prioriza el CSV de la red reducida). 1985–2022 no
se toca.

Para forzar la reconstrucción de un rango (reparaciones manuales), usa
`--recalcular`.

Uso:
    python -m actualizacion.sync_clima_hist --desde 2026-10 --hasta 2026-10
    python -m actualizacion.sync_clima_hist --todo
    python -m actualizacion.sync_clima_hist --recalcular --desde 2023-01 --hasta 2026-10
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from comun.constants import ANIO_MINIMO
from comun.db import exec_sql_file, get_engine, log_carga, render_sql

SQL_DDL = Path(__file__).resolve().parent / "sql" / "12_estatal_csv.sql"

SQL_ULTIMO = "SELECT MAX(DATEFROMPARTS([Año], Mes, 1)) FROM dbo.clima_hist"

SQL_ENTIDADES_MES = """
SELECT COUNT(DISTINCT Estado)
FROM dbo.clima_hist
WHERE [Año] = ? AND Mes = ?
"""

SQL_MESES_COMPLETOS = """
SELECT anio, mes
FROM {{schema}}.vw_clima_estatal_vigente
WHERE DATEFROMPARTS(anio, mes, 1) BETWEEN ? AND ?
GROUP BY anio, mes
HAVING COUNT(DISTINCT cve_ent) >= 32
   AND COUNT(DISTINCT variable_id) >= 4
ORDER BY anio, mes
"""

SQL_BORRA = """
DELETE ch
FROM dbo.clima_hist ch
JOIN (VALUES __VALORES__) AS c(anio, mes)
  ON c.anio = ch.[Año] AND c.mes = ch.Mes
"""

SQL_INSERTA = """
;WITH objetivos AS (
    SELECT * FROM (VALUES __VALORES__) AS v(anio, mes)
),
base AS (
    SELECT h.anio, h.mes,
           COALESCE(m.nom_hist, en.nom_ent) AS Estado,
           MAX(CASE WHEN v.codigo = 'PREC' THEN h.valor END) AS Precipitacion,
           MAX(CASE WHEN v.codigo = 'TMAX' THEN h.valor END) AS Tmax,
           MAX(CASE WHEN v.codigo = 'TMED' THEN h.valor END) AS Tmed,
           MAX(CASE WHEN v.codigo = 'TMIN' THEN h.valor END) AS Tmin
    FROM {{schema}}.vw_clima_estatal_vigente h
    JOIN objetivos o ON o.anio = h.anio AND o.mes = h.mes
    JOIN {{schema}}.entidad en ON en.cve_ent = h.cve_ent
    JOIN {{schema}}.variable v ON v.variable_id = h.variable_id
    LEFT JOIN (VALUES
        ('05', N'Coahuila'),
        ('15', N'Estado de México'),
        ('16', N'Michoacán'),
        ('30', N'Veracruz')
    ) AS m(cve_ent, nom_hist) ON m.cve_ent = h.cve_ent
    GROUP BY h.anio, h.mes, h.cve_ent, en.nom_ent, m.nom_hist
)
INSERT INTO dbo.clima_hist
    (FECHA, Estado, [Año], Mes, Precipitacion, Tmax, Tmed, Tmin, Tdiff)
SELECT DATEFROMPARTS(anio, mes, 1), Estado, anio, mes,
       Precipitacion, Tmax, Tmed, Tmin,
       ROUND(Tmax - Tmin, 2)
FROM base
WHERE Tmax IS NOT NULL AND Tmin IS NOT NULL
"""

SQL_CUENTA = """
SELECT COUNT(*)
FROM dbo.clima_hist ch
JOIN (VALUES __VALORES__) AS c(anio, mes)
  ON c.anio = ch.[Año] AND c.mes = ch.Mes
"""


def month_start(value: str | None, default: date) -> date:
    if not value:
        return default
    parts = value.split("-")
    return date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)


def mes_anterior(hoy: date | None = None) -> date:
    hoy = hoy or date.today()
    if hoy.month == 1:
        return date(hoy.year - 1, 12, 1)
    return date(hoy.year, hoy.month - 1, 1)


def sincronizar_clima_hist(
    engine, desde: date, hasta: date, recalcular: bool = False
) -> int:
    """Agrega a dbo.clima_hist solo los meses nuevos (o el último incompleto).

    `desde`/`hasta` acotan los meses candidatos. Devuelve las filas escritas.
    """
    desde = max(desde, date(ANIO_MINIMO, 1, 1))
    if desde > hasta:
        return 0

    exec_sql_file(engine, SQL_DDL)

    with engine.begin() as conn:
        existe = conn.exec_driver_sql("SELECT OBJECT_ID('dbo.clima_hist', 'U')").scalar()
        if existe is None:
            print("  [aviso] dbo.clima_hist no existe; no se sincroniza")
            return 0

        ultimo = conn.exec_driver_sql(SQL_ULTIMO).scalar()
        ultimo = ultimo.date() if hasattr(ultimo, "date") else ultimo

        completos = conn.exec_driver_sql(
            render_sql(SQL_MESES_COMPLETOS), (desde, hasta)
        ).all()
        if not completos:
            print("  [aviso] no hay meses completos en la fuente vigente")
            return 0

        if recalcular:
            objetivo = [(int(a), int(m)) for a, m in completos]
        else:
            objetivo = []
            for anio, mes in completos:
                ym = date(int(anio), int(mes), 1)
                if ultimo is None or ym > ultimo:
                    objetivo.append((int(anio), int(mes)))
                elif ym == ultimo:
                    entidades = conn.exec_driver_sql(
                        SQL_ENTIDADES_MES, (anio, mes)
                    ).scalar_one()
                    if int(entidades) < 32:
                        objetivo.append((int(anio), int(mes)))

        if not objetivo:
            print("  clima_hist ya está al día; no hay meses nuevos")
            return 0

        valores = ", ".join(f"({anio}, {mes})" for anio, mes in objetivo)
        conn.exec_driver_sql(SQL_BORRA.replace("__VALORES__", valores))
        conn.exec_driver_sql(render_sql(SQL_INSERTA.replace("__VALORES__", valores)))
        filas = conn.exec_driver_sql(
            render_sql(SQL_CUENTA.replace("__VALORES__", valores))
        ).scalar_one()

    print(
        "  clima_hist: "
        + ", ".join(f"{a}-{m:02d}" for a, m in objetivo)
        + f" ({filas} filas)"
    )
    return int(filas)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza la serie estatal con dbo.clima_hist (2023+)."
    )
    parser.add_argument("--desde", default=None, help="YYYY o YYYY-MM.")
    parser.add_argument("--hasta", default=None, help="YYYY o YYYY-MM.")
    parser.add_argument("--todo", action="store_true",
                        help=f"Desde {ANIO_MINIMO}-01 hasta el mes anterior.")
    parser.add_argument("--recalcular", action="store_true",
                        help="Reescribe todos los meses completos del rango.")
    args = parser.parse_args()

    if args.todo:
        desde = date(ANIO_MINIMO, 1, 1)
        hasta = mes_anterior()
    else:
        desde = month_start(args.desde, date(ANIO_MINIMO, 1, 1))
        hasta = month_start(args.hasta, mes_anterior())
        desde = max(desde, date(ANIO_MINIMO, 1, 1))

    if desde > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    engine = get_engine()
    with log_carga(engine, "sync_clima_hist") as info:
        info["filas"] = sincronizar_clima_hist(
            engine, desde, hasta, recalcular=args.recalcular
        )
        info["mensaje"] = (
            f"rango {desde:%Y-%m}..{hasta:%Y-%m}; "
            f"recalcular {args.recalcular}"
        )

    print(
        f"clima_hist {desde:%Y-%m}..{hasta:%Y-%m}: "
        f"{info['filas']:,} filas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
