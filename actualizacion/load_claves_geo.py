"""Asigna la clave de municipio (cvegeo) y de estado (cve_ent) a dbo.Clientes y dbo.CEDIS.

El cálculo geométrico se ejecuta en SQL Server con los índices espaciales de
`datos_publicos.municipio` y `datos_publicos.entidad`. Python solo orquesta
por lotes para no abrir transacciones largas ni bloquear las tablas de dbo.

Reglas:
  - Solo se rellenan filas con cvegeo/cve_ent NULL; nunca se sobrescribe.
  - cve_ent se deriva de LEFT(cvegeo, 2).
  - Si el punto no cae en ningún municipio, se usa el polígono de entidad.
  - Si la coordenada es inválida, se usa el texto Estado y, si hace falta,
    Ciudad (solo para cve_ent).

Uso:
    python -m actualizacion.load_claves_geo
    python -m actualizacion.load_claves_geo --tabla clientes --limite 2000
    python -m actualizacion.load_claves_geo --tabla cedis
    python -m actualizacion.load_claves_geo --batch 5000
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from comun.db import exec_sql_file, get_engine, log_carga, render_sql

SQL_DDL = Path(__file__).resolve().parent / "sql" / "10_claves_geo_dbo.sql"

# Bounding box de México. Fuera de aquí la coordenada se considera inválida.
LAT_MIN, LAT_MAX = 14.0, 33.0
LON_MIN, LON_MAX = -118.0, -86.0


@dataclass(frozen=True)
class Tabla:
    nombre: str
    tabla: str
    clave: tuple[str, ...]
    tipos: tuple[str, ...]
    lat: str
    lon: str
    estado: str
    ciudad: str

    @property
    def cols_k(self) -> list[str]:
        return [f"k{i + 1}" for i in range(len(self.clave))]

    @property
    def filtro_coords(self) -> str:
        return (
            f"[{self.lat}] BETWEEN {LAT_MIN} AND {LAT_MAX} "
            f"AND [{self.lon}] BETWEEN {LON_MIN} AND {LON_MAX}"
        )

    @property
    def join_dbo(self) -> str:
        return " AND ".join(
            f"p.{k} = c.[{col}]" for k, col in zip(self.cols_k, self.clave)
        )


TABLAS: dict[str, Tabla] = {
    "clientes": Tabla(
        nombre="clientes",
        tabla="dbo.Clientes",
        clave=("Cliente_id", "Direccion_id"),
        tipos=("VARCHAR(255)", "SMALLINT"),
        lat="Lat",
        lon="Lon",
        estado="Estado",
        ciudad="Ciudad",
    ),
    "cedis": Tabla(
        nombre="cedis",
        tabla="dbo.CEDIS",
        clave=("CEDIS",),
        tipos=("SMALLINT",),
        lat="Latitud",
        lon="Longitud",
        estado="ESTADO",
        ciudad="CIUDAD",
    ),
}


def resumen(conn, t: Tabla) -> dict:
    sql = f"""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN cvegeo IS NOT NULL THEN 1 ELSE 0 END) AS con_municipio,
        SUM(CASE WHEN cve_ent IS NOT NULL THEN 1 ELSE 0 END) AS con_estado,
        SUM(CASE WHEN cvegeo IS NULL OR cve_ent IS NULL THEN 1 ELSE 0 END) AS pendientes
    FROM {t.tabla};
    """
    return dict(conn.exec_driver_sql(sql).mappings().one())


def derivar_estado(conn, t: Tabla) -> int:
    """Completa cve_ent cuando ya existe cvegeo."""
    sql = f"""
    SET NOCOUNT ON;
    UPDATE {t.tabla}
    SET cve_ent = LEFT(cvegeo, 2)
    WHERE cvegeo IS NOT NULL AND cve_ent IS NULL;
    SELECT @@ROWCOUNT;
    """
    return int(conn.exec_driver_sql(sql).scalar() or 0)


def crear_pendientes(conn, t: Tabla, limite: int | None) -> int:
    """Copia a una tabla temporal solo los puntos que aún no tienen clave."""
    columnas = ", ".join(
        f"{k} {tipo}" for k, tipo in zip(t.cols_k, t.tipos)
    )
    conn.exec_driver_sql(
        "CREATE TABLE #pend ("
        "id INT IDENTITY(1,1) PRIMARY KEY, "
        f"{columnas}, "
        "lat FLOAT NOT NULL, lon FLOAT NOT NULL, "
        "cvegeo CHAR(5) NULL, cve_ent CHAR(2) NULL, "
        "procesado BIT NOT NULL DEFAULT 0, "
        "procesado_estado BIT NOT NULL DEFAULT 0);"
    )
    top = f"TOP ({limite}) " if limite else ""
    seleccion = ", ".join(f"[{c}]" for c in t.clave)
    conn.exec_driver_sql(
        f"INSERT INTO #pend ({', '.join(t.cols_k)}, lat, lon) "
        f"SELECT {top}{seleccion}, [{t.lat}], [{t.lon}] "
        f"FROM {t.tabla} "
        f"WHERE cvegeo IS NULL AND {t.filtro_coords};"
    )
    return int(conn.exec_driver_sql("SELECT COUNT(*) FROM #pend;").scalar() or 0)


def procesar_lote(conn, t: Tabla, desde: int, hasta: int) -> int:
    """Resuelve un lote de puntos contra el polígono de municipio y actualiza dbo."""
    sql = f"""
    SET NOCOUNT ON;

    ;WITH lote AS (
        SELECT id, lat, lon
        FROM #pend
        WHERE id BETWEEN {desde} AND {hasta} AND procesado = 0
    ),
    matches AS (
        SELECT l.id, m.cvegeo,
               ROW_NUMBER() OVER (PARTITION BY l.id ORDER BY m.cvegeo) AS rn
        FROM lote l
        JOIN {{{{schema}}}}.municipio m
          ON m.geom.STIntersects(geography::Point(l.lat, l.lon, 4326)) = 1
    )
    UPDATE p
    SET cvegeo = mt.cvegeo,
        cve_ent = LEFT(mt.cvegeo, 2),
        procesado = 1
    FROM #pend p
    JOIN matches mt ON mt.id = p.id
    WHERE mt.rn = 1;

    -- Los que no cayeron en ningún municipio también quedan procesados.
    UPDATE #pend
    SET procesado = 1
    WHERE id BETWEEN {desde} AND {hasta} AND procesado = 0;

    UPDATE c
    SET cvegeo = p.cvegeo,
        cve_ent = p.cve_ent
    FROM {t.tabla} c
    JOIN #pend p ON {t.join_dbo}
    WHERE p.id BETWEEN {desde} AND {hasta}
      AND p.cvegeo IS NOT NULL;

    SELECT @@ROWCOUNT;
    """
    return int(conn.exec_driver_sql(render_sql(sql)).scalar() or 0)


def procesar_estado_lote(conn, t: Tabla, desde: int, hasta: int) -> int:
    """Para los puntos del lote sin municipio, usa el polígono de entidad."""
    sql = f"""
    SET NOCOUNT ON;

    ;WITH lote AS (
        SELECT id, lat, lon
        FROM #pend
        WHERE id BETWEEN {desde} AND {hasta}
          AND cvegeo IS NULL
          AND procesado_estado = 0
    ),
    matches AS (
        SELECT l.id, e.cve_ent,
               ROW_NUMBER() OVER (PARTITION BY l.id ORDER BY e.cve_ent) AS rn
        FROM lote l
        JOIN {{{{schema}}}}.entidad e
          ON e.geom.STIntersects(geography::Point(l.lat, l.lon, 4326)) = 1
    )
    UPDATE p
    SET cve_ent = mt.cve_ent,
        procesado_estado = 1
    FROM #pend p
    JOIN matches mt ON mt.id = p.id
    WHERE mt.rn = 1;

    UPDATE #pend
    SET procesado_estado = 1
    WHERE id BETWEEN {desde} AND {hasta}
      AND cvegeo IS NULL
      AND procesado_estado = 0;

    UPDATE c
    SET cve_ent = p.cve_ent
    FROM {t.tabla} c
    JOIN #pend p ON {t.join_dbo}
    WHERE p.id BETWEEN {desde} AND {hasta}
      AND p.cvegeo IS NULL
      AND p.cve_ent IS NOT NULL;

    SELECT @@ROWCOUNT;
    """
    return int(conn.exec_driver_sql(render_sql(sql)).scalar() or 0)


def fallback_texto(conn, t: Tabla) -> tuple[int, int]:
    """Fallback por texto: Estado y, si hace falta, Ciudad (solo cve_ent)."""
    estado_sql = f"""
    SET NOCOUNT ON;
    UPDATE c
    SET cve_ent = e.cve_ent
    FROM {t.tabla} c
    JOIN {{{{schema}}}}.entidad e
      ON UPPER(LTRIM(RTRIM(c.[{t.estado}]))) COLLATE Latin1_General_CI_AI =
         UPPER(LTRIM(RTRIM(e.nom_ent))) COLLATE Latin1_General_CI_AI
    WHERE c.cve_ent IS NULL
      AND c.[{t.estado}] IS NOT NULL
      AND LTRIM(RTRIM(c.[{t.estado}])) <> '';
    SELECT @@ROWCOUNT;
    """
    por_estado = int(conn.exec_driver_sql(render_sql(estado_sql)).scalar() or 0)

    ciudad_sql = f"""
    SET NOCOUNT ON;

    ;WITH ciudades AS (
        SELECT UPPER(LTRIM(RTRIM(c.[{t.ciudad}]))) COLLATE Latin1_General_CI_AI AS ciudad,
               MIN(m.cve_ent) AS cve_ent,
               COUNT(DISTINCT m.cve_ent) AS estados
        FROM {t.tabla} c
        JOIN {{{{schema}}}}.municipio m
          ON UPPER(LTRIM(RTRIM(c.[{t.ciudad}]))) COLLATE Latin1_General_CI_AI =
             UPPER(LTRIM(RTRIM(m.nom_mun))) COLLATE Latin1_General_CI_AI
        WHERE c.cve_ent IS NULL
        GROUP BY UPPER(LTRIM(RTRIM(c.[{t.ciudad}]))) COLLATE Latin1_General_CI_AI
    )
    UPDATE c
    SET cve_ent = ci.cve_ent
    FROM {t.tabla} c
    JOIN ciudades ci
      ON UPPER(LTRIM(RTRIM(c.[{t.ciudad}]))) COLLATE Latin1_General_CI_AI = ci.ciudad
    WHERE c.cve_ent IS NULL AND ci.estados = 1;

    SELECT @@ROWCOUNT;
    """
    por_ciudad = int(conn.exec_driver_sql(render_sql(ciudad_sql)).scalar() or 0)
    return por_estado, por_ciudad


def procesar_tabla(conn, t: Tabla, batch: int, limite: int | None) -> dict:
    inicio = time.monotonic()
    antes = resumen(conn, t)
    derivadas = derivar_estado(conn, t)
    pendientes = crear_pendientes(conn, t, limite)
    fin_copia = time.monotonic()

    por_municipio = 0
    while True:
        desde = conn.exec_driver_sql(
            "SELECT MIN(id) FROM #pend WHERE procesado = 0;"
        ).scalar()
        if desde is None:
            break
        por_municipio += procesar_lote(
            conn, t, int(desde), int(desde) + batch - 1
        )
    fin_municipio = time.monotonic()

    # Solo se revisan los puntos de este lote que no cayeron en un municipio.
    por_entidad = 0
    while True:
        desde = conn.exec_driver_sql(
            "SELECT MIN(id) FROM #pend "
            "WHERE cvegeo IS NULL AND procesado_estado = 0;"
        ).scalar()
        if desde is None:
            break
        por_entidad += procesar_estado_lote(
            conn, t, int(desde), int(desde) + batch - 1
        )
    fin_entidad = time.monotonic()

    conn.exec_driver_sql("DROP TABLE #pend;")

    por_estado, por_ciudad = fallback_texto(conn, t)
    despues = resumen(conn, t)
    fin_total = time.monotonic()

    return {
        "tabla": t.tabla,
        "antes": antes,
        "despues": despues,
        "pendientes_copiados": pendientes,
        "derivadas": derivadas,
        "por_municipio": por_municipio,
        "por_entidad": por_entidad,
        "por_texto_estado": por_estado,
        "por_texto_ciudad": por_ciudad,
        "actualizadas": antes["pendientes"] - despues["pendientes"],
        "duracion": {
            "copia": fin_copia - inicio,
            "municipio": fin_municipio - fin_copia,
            "entidad": fin_entidad - fin_municipio,
            "texto": fin_total - fin_entidad,
            "total": fin_total - inicio,
        },
    }


def imprimir(resultado: dict) -> None:
    a = resultado["antes"]
    d = resultado["despues"]
    t = resultado["duracion"]
    print(
        f"\n{resultado['tabla']}: {d['total']:,} filas\n"
        f"  con municipio : {a['con_municipio']:,} -> {d['con_municipio']:,}\n"
        f"  con estado    : {a['con_estado']:,} -> {d['con_estado']:,}\n"
        f"  pendientes    : {a['pendientes']:,} -> {d['pendientes']:,}\n"
        f"  resueltas     : {resultado['actualizadas']:,} "
        f"(municipio {resultado['por_municipio']:,}, "
        f"entidad {resultado['por_entidad']:,}, "
        f"texto estado {resultado['por_texto_estado']:,}, "
        f"texto ciudad {resultado['por_texto_ciudad']:,}, "
        f"derivadas {resultado['derivadas']:,})\n"
        f"  tiempo        : copia {t['copia']:.1f}s, "
        f"municipio {t['municipio']:.1f}s, "
        f"entidad {t['entidad']:.1f}s, "
        f"texto {t['texto']:.1f}s, "
        f"total {t['total']:.1f}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Asigna cvegeo y cve_ent a dbo.Clientes y dbo.CEDIS."
    )
    parser.add_argument(
        "--tabla",
        choices=("ambas", "clientes", "cedis"),
        default="ambas",
        help="Tabla a procesar (default: ambas).",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=5000,
        help="Filas por lote del join espacial (default: 5000).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Máximo de filas pendientes por tabla; útil para pruebas.",
    )
    args = parser.parse_args()

    if args.batch < 1:
        raise SystemExit("--batch debe ser mayor o igual a 1")
    if args.limite is not None and args.limite < 1:
        raise SystemExit("--limite debe ser mayor o igual a 1")

    engine = get_engine()
    exec_sql_file(engine, SQL_DDL)

    nombres = ("clientes", "cedis") if args.tabla == "ambas" else (args.tabla,)
    resultados: list[dict] = []

    with log_carga(engine, "load_claves_geo") as info:
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            for nombre in nombres:
                resultados.append(
                    procesar_tabla(conn, TABLAS[nombre], args.batch, args.limite)
                )

        for resultado in resultados:
            imprimir(resultado)

        total = sum(r["actualizadas"] for r in resultados)
        info["filas"] = total
        info["mensaje"] = "; ".join(
            f"{r['tabla']}: {r['despues']['con_municipio']} con municipio, "
            f"{r['despues']['con_estado']} con estado, "
            f"{r['despues']['pendientes']} pendientes"
            for r in resultados
        )

    print(f"\nTotal de filas actualizadas: {total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
