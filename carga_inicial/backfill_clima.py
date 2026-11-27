"""Carga de clima 2023 a la fecha (operación de una sola vez).

Es un envoltorio de `actualizacion/` para dejar en `carga_inicial/` el punto de
entrada de la carga inicial de clima. El loader real es el mismo que se usa a
diario, pero aquí se invoca con el rango completo permitido.

Ventana de carga: desde 2023-01-01 a la fecha. No se carga el histórico
anterior.

Uso:
    python -m carga_inicial.backfill_clima
    python -m carga_inicial.backfill_clima --tipo diario
    python -m carga_inicial.backfill_clima --desde 2023-01-01 --hasta 2025-12-31
    python -m carga_inicial.backfill_clima --sin-calculo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date

from comun.constants import DESDE_MINIMO, clamp_desde


def run_module(module: str, argv: list[str]) -> tuple[str, int]:
    cmd = [sys.executable, "-m", module, *argv]
    print("\n$ " + " ".join(cmd))
    result = subprocess.run(cmd)
    return module, result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga histórica de clima.")
    parser.add_argument("--tipo", choices=("diario", "mensual", "ambos"), default="ambos")
    parser.add_argument("--desde", default=DESDE_MINIMO.isoformat(),
                        help=f"YYYY-MM-DD (mínimo {DESDE_MINIMO.isoformat()})")
    parser.add_argument("--hasta", default=None, help="YYYY-MM-DD (default: hoy)")
    parser.add_argument("--sin-calculo", action="store_true",
                        help="No construir la serie mensual propia al final.")
    parser.add_argument("--sin-sitios", action="store_true",
                        help="No derivar el clima de sitios.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    desde_solicitado = date.fromisoformat(args.desde)
    if desde_solicitado < DESDE_MINIMO:
        print(
            f"Aviso: la ventana mínima es {DESDE_MINIMO}; "
            f"se usa {DESDE_MINIMO} en lugar de {desde_solicitado}."
        )
    desde = clamp_desde(desde_solicitado)
    hasta = date.fromisoformat(args.hasta) if args.hasta else date.today()
    if desde > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    pasos: list[tuple[str, list[str]]] = []
    if args.tipo in ("diario", "ambos"):
        pasos.append((
            "actualizacion.load_clima_smn",
            ["--tipo", "diario", "--desde", desde.isoformat(), "--hasta", hasta.isoformat()]
            + (["--dry-run"] if args.dry_run else []),
        ))
    if args.tipo in ("mensual", "ambos"):
        pasos.append((
            "actualizacion.load_clima_smn",
            ["--tipo", "mensual", "--desde", str(desde.year), "--hasta", str(hasta.year)]
            + (["--dry-run"] if args.dry_run else []),
        ))
    if not args.sin_calculo:
        pasos.append((
            "actualizacion.build_mensual",
            ["--desde", f"{desde.year:04d}-{desde.month:02d}",
             "--hasta", f"{hasta.year:04d}-{hasta.month:02d}"]
            + (["--sin-sitios"] if args.sin_sitios else [])
            + (["--dry-run"] if args.dry_run else []),
        ))

    print(f"Carga histórica de clima: {desde} -> {hasta}")
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

    print("\nCarga histórica terminada correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
