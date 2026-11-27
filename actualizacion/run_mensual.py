"""Flujo de actualización mensual.

Hace, en orden:
  1. Carga los TXT mensuales oficiales del SMN para el rango de años.
  2. Recalcula la serie mensual propia (CALCULADO) para ese rango.
  3. Opcionalmente recalcula el clima mensual de los sitios.

Ventana de carga: 2023 a la fecha. No se carga el histórico anterior.

La carga oficial y el cálculo propio son pasos independientes: si el SMN
falla, el cálculo propio puede seguir corriendo con los diarios ya cargados.

Ejemplos:
    python -m actualizacion.run_mensual
    python -m actualizacion.run_mensual --desde 2025 --hasta 2025
    python -m actualizacion.run_mensual --completo
    python -m actualizacion.run_mensual --solo-calculo --desde 2025-01 --hasta 2025-12
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date

from comun.constants import ANIO_MINIMO


def run_module(module: str, argv: list[str]) -> tuple[str, int]:
    cmd = [sys.executable, "-m", module, *argv]
    print("\n$ " + " ".join(cmd))
    result = subprocess.run(cmd)
    return module, result.returncode


def year_of(value: str | None, default: int) -> int:
    if not value:
        return default
    return int(value.split("-")[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Actualización mensual de clima.")
    parser.add_argument("--desde", default=None, help="YYYY o YYYY-MM")
    parser.add_argument("--hasta", default=None, help="YYYY o YYYY-MM")
    parser.add_argument("--completo", action="store_true",
                        help=f"Recargar todo el rango permitido ({ANIO_MINIMO} a la fecha).")
    parser.add_argument("--solo-oficial", action="store_true",
                        help="Solo cargar el TXT oficial; no recalcular.")
    parser.add_argument("--solo-calculo", action="store_true",
                        help="Solo recalcular; no cargar el TXT oficial.")
    parser.add_argument("--sin-sitios", action="store_true",
                        help="No recalcular el clima mensual de sitios.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.solo_oficial and args.solo_calculo:
        raise SystemExit("--solo-oficial y --solo-calculo son excluyentes")

    hoy = date.today()
    desde_year = ANIO_MINIMO if args.completo else year_of(args.desde, hoy.year - 1)
    if desde_year < ANIO_MINIMO:
        print(
            f"Aviso: la ventana mínima es {ANIO_MINIMO}; "
            f"se usa {ANIO_MINIMO} en lugar de {desde_year}."
        )
        desde_year = ANIO_MINIMO
    hasta_year = year_of(args.hasta, hoy.year)
    if desde_year > hasta_year:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    pasos: list[tuple[str, list[str]]] = []
    if not args.solo_calculo:
        pasos.append((
            "actualizacion.load_clima_smn",
            ["--tipo", "mensual",
             "--desde", str(desde_year),
             "--hasta", str(hasta_year)]
            + (["--dry-run"] if args.dry_run else []),
        ))
    if not args.solo_oficial:
        pasos.append((
            "actualizacion.build_mensual",
            ["--desde", f"{desde_year:04d}-01",
             "--hasta", f"{hasta_year:04d}-12"]
            + (["--sin-sitios"] if args.sin_sitios else [])
            + (["--dry-run"] if args.dry_run else []),
        ))

    print(f"Actualización mensual: años {desde_year}..{hasta_year}")
    fallos: list[tuple[str, int]] = []
    for module, argv in pasos:
        nombre, code = run_module(module, argv)
        if code != 0:
            fallos.append((nombre, code))

    if fallos:
        print("\nPasos con error:")
        for nombre, code in fallos:
            print(f"  - {nombre} (código {code})")
        return 1

    print("\nActualización mensual terminada correctamente.")
    print("Revisa las queries de control en actualizacion/queries/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
