"""Carga inicial y actualizaciones ocasionales del modelo homologado.

Este runner NO actualiza clima del día a día. Sirve para:
  * crear las estructuras (tablas, índices, vistas, catálogos);
  * cargar o recargar geografía del INEGI;
  * cargar el catálogo de estaciones del SMN;
  * cargar sitios propios y emparejarlos con estaciones;
  * cargar demografía/social por municipio, localidad o AGEB;
  * migrar dbo.clima_hist.

Ejemplos:
    # Estructuras + catálogos
    python -m carga_inicial.run_inicial --init

    # Estructuras + geografía + estaciones + sitios
    python -m carga_inicial.run_inicial --init \
        --mg-dir /datos/mg_2025 --sitios data/sitios.csv

    # Solo recargar geografía
    python -m carga_inicial.run_inicial --solo inegi --mg-dir /datos/mg_2025

    # Solo migrar la tabla histórica (2023+)
    python -m carga_inicial.run_inicial --migrar

    # Purgar datos climáticos anteriores a 2023
    python -m carga_inicial.run_inicial --purgar

La carga inicial de clima (2023 a la fecha) se hace una sola vez con:
    python -m carga_inicial.backfill_clima
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from comun.db import create_database, create_schema, exec_sql_file, get_engine

SQL_DIR = Path(__file__).resolve().parent / "sql"

SQL_BASE = [
    "01a_catalogos.sql",
    "01b_geografia.sql",
    "01c_estaciones_sitios.sql",
    "01d_hechos_clima.sql",
    "01e_demografia.sql",
    "02_indices.sql",
    "03_vistas.sql",
    "04_catalogos.sql",
]

PASOS = ["schema", "purgar", "inegi", "estaciones", "sitios", "match", "demografia"]


def run_module(module: str, argv: list[str]) -> None:
    cmd = [sys.executable, "-m", module, *argv]
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def aplicar_schema(
    migrar: bool = False,
    crear_base: bool = True,
    crear_esquema: bool = True,
) -> None:
    if crear_base:
        db = create_database()
        print(f"  base de datos asegurada: {db}")
    schema = create_schema() if crear_esquema else None
    if schema:
        print(f"  schema asegurado: {schema}")
    engine = get_engine()
    for nombre in SQL_BASE:
        print(f"  aplicando carga_inicial/sql/{nombre}")
        exec_sql_file(engine, SQL_DIR / nombre, schema=schema)
    if migrar:
        aplicar_migracion(engine, schema=schema)


def aplicar_migracion(engine=None, schema=None) -> None:
    engine = engine or get_engine()
    print("  aplicando carga_inicial/sql/05_migrar_clima_hist.sql")
    exec_sql_file(engine, SQL_DIR / "05_migrar_clima_hist.sql", schema=schema)


def aplicar_purga(engine=None, schema=None) -> None:
    engine = engine or get_engine()
    print("  aplicando carga_inicial/sql/06_purgar_antes_2023.sql")
    exec_sql_file(engine, SQL_DIR / "06_purgar_antes_2023.sql", schema=schema)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carga inicial y actualizaciones ocasionales."
    )
    parser.add_argument("--init", action="store_true",
                        help="Crear la base/schema (si no existen), tablas, índices, vistas y catálogos.")
    parser.add_argument("--sin-crear-base", action="store_true",
                        help="No intentar CREATE DATABASE; usar una base ya existente.")
    parser.add_argument("--sin-crear-esquema", action="store_true",
                        help="No intentar CREATE SCHEMA; usar un schema ya existente.")
    parser.add_argument("--migrar", action="store_true",
                        help="Migrar dbo.clima_hist al modelo nuevo (solo 2023+).")
    parser.add_argument("--purgar", action="store_true",
                        help="Borrar datos climáticos anteriores a 2023.")
    parser.add_argument("--mg-dir", default=None,
                        help="Carpeta del Marco Geoestadístico del INEGI.")
    parser.add_argument("--mg-version", default="2025")
    parser.add_argument("--entidades", default="",
                        help="Entidades a cargar del MG (ej. 01,06).")
    parser.add_argument("--skip-ageb", action="store_true")
    parser.add_argument("--sitios", default=None,
                        help="CSV/Excel de sitios propios.")
    parser.add_argument("--sitios-hoja", default=None)
    parser.add_argument("--k", type=int, default=5,
                        help="Estaciones vecinas por sitio.")
    parser.add_argument("--demografia", default=None,
                        help="Archivo de indicadores demográficos.")
    parser.add_argument("--demografia-nivel", default="municipio",
                        choices=("municipio", "localidad", "ageb"))
    parser.add_argument("--demografia-anio", type=int, default=None)
    parser.add_argument("--demografia-fuente", default="INEGI_CENSO")
    parser.add_argument("--demografia-formato", default="auto",
                        choices=("auto", "largo", "ancho"))
    parser.add_argument("--solo", default="", help="Pasos separados por coma.")
    parser.add_argument("--saltar", default="", help="Pasos a omitir, separados por coma.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    solo = {p.strip() for p in args.solo.split(",") if p.strip()}
    saltar = {p.strip() for p in args.saltar.split(",") if p.strip()}

    def activo(paso: str) -> bool:
        if solo:
            return paso in solo
        return paso not in saltar

    # 1) Esquema
    if activo("schema") and (args.init or "schema" in solo):
        print("== Esquema ==")
        aplicar_schema(
            args.migrar,
            crear_base=not args.sin_crear_base,
            crear_esquema=not args.sin_crear_esquema,
        )
    elif args.migrar:
        print("== Migración clima_hist ==")
        aplicar_migracion()

    # 1b) Purga de datos anteriores a 2023
    if activo("purgar") and (args.purgar or "purgar" in solo):
        print("== Purga anterior a 2023 ==")
        aplicar_purga()

    # 2) Geografía INEGI
    if activo("inegi") and args.mg_dir:
        argv = ["--mg-dir", args.mg_dir, "--version", args.mg_version, "--reload"]
        if args.entidades:
            argv += ["--entidades", args.entidades]
        if args.skip_ageb:
            argv += ["--skip-ageb"]
        print("\n== Geografía INEGI ==")
        run_module("carga_inicial.load_inegi", argv)

    # 3) Estaciones SMN
    if activo("estaciones"):
        print("\n== Estaciones SMN ==")
        argv = ["--skip-geo"] if not args.mg_dir else []
        run_module("carga_inicial.load_estaciones", argv)

    # 4) Sitios propios
    if activo("sitios") and args.sitios:
        print("\n== Sitios propios ==")
        argv = ["--archivo", args.sitios]
        if args.sitios_hoja:
            argv += ["--hoja", args.sitios_hoja]
        run_module("carga_inicial.load_sitios", argv)

    # 5) Puente sitio-estación
    if activo("match") and (args.sitios or "match" in solo):
        print("\n== Sitios vs estaciones ==")
        run_module("carga_inicial.match_sitio_estacion", ["--k", str(args.k)])

    # 6) Demografía
    if activo("demografia") and args.demografia:
        print("\n== Demografía ==")
        argv = [
            "--nivel", args.demografia_nivel,
            "--archivo", args.demografia,
            "--fuente", args.demografia_fuente,
            "--formato", args.demografia_formato,
        ]
        if args.demografia_anio:
            argv += ["--anio", str(args.demografia_anio)]
        if args.dry_run:
            argv += ["--dry-run"]
        run_module("carga_inicial.load_demografia", argv)

    print("\nCarga inicial/ocasional terminada.")
    print("Para el día a día usa: python -m actualizacion.run_diario")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
