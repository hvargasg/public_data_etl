"""Flujo de actualización diaria.

Hace, en orden:
  1. Carga los TXT diarios recientes del SMN (por defecto).
  2. Opcionalmente carga los CSV diarios del SIH (--sih).
  3. Recalcula la serie mensual propia para los meses tocados.

Ventana de carga: 2023-01-01 a la fecha. No se carga el histórico anterior.

Los pasos son independientes: si el SIH falla (por ejemplo, por el WAF), el
script continúa con el cálculo mensual y reporta el fallo al final.

Ejemplos:
    python -m actualizacion.run_diario
    python -m actualizacion.run_diario --dias 7
    python -m actualizacion.run_diario --sih --dias 30
    python -m actualizacion.run_diario --desde 2025-01-01 --hasta 2025-01-31
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta

from comun.constants import DESDE_MINIMO, clamp_desde


def run_module(module: str, argv: list[str]) -> tuple[str, int]:
    cmd = [sys.executable, "-m", module, *argv]
    print("\n$ " + " ".join(cmd))
    result = subprocess.run(cmd)
    return module, result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Actualización diaria de clima.")
    parser.add_argument("--dias", type=int, default=30,
                        help="Días hacia atrás si no se indica --desde (default 30).")
    parser.add_argument("--desde", default=None, help="YYYY-MM-DD")
    parser.add_argument("--hasta", default=None, help="YYYY-MM-DD")
    parser.add_argument("--sih", action="store_true",
                        help="Incluir la carga de CSV diarios del SIH.")
    parser.add_argument("--sin-smn", action="store_true",
                        help="No cargar los TXT diarios del SMN.")
    parser.add_argument("--sin-sitios", action="store_true",
                        help="No recalcular el clima mensual de sitios.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hasta = date.fromisoformat(args.hasta) if args.hasta else date.today()
    desde_solicitado = (
        date.fromisoformat(args.desde)
        if args.desde
        else hasta - timedelta(days=max(1, args.dias) - 1)
    )
    if desde_solicitado < DESDE_MINIMO:
        print(
            f"Aviso: la ventana mínima es {DESDE_MINIMO}; "
            f"se usa {DESDE_MINIMO} en lugar de {desde_solicitado}."
        )
    desde = clamp_desde(desde_solicitado)
    if desde > hasta:
        raise SystemExit("--desde no puede ser mayor que --hasta")

    meses = (
        f"{desde.year:04d}-{desde.month:02d}",
        f"{hasta.year:04d}-{hasta.month:02d}",
    )

    pasos: list[tuple[str, list[str]]] = []
    if not args.sin_smn:
        pasos.append((
            "actualizacion.load_clima_smn",
            ["--tipo", "diario", "--desde", desde.isoformat(), "--hasta", hasta.isoformat()]
            + (["--dry-run"] if args.dry_run else []),
        ))
    if args.sih:
        pasos.append((
            "actualizacion.load_clima_sih",
            ["--desde", desde.isoformat(), "--hasta", hasta.isoformat()]
            + (["--dry-run"] if args.dry_run else []),
        ))
    pasos.append((
        "actualizacion.build_mensual",
        ["--desde", meses[0], "--hasta", meses[1]]
        + (["--sin-sitios"] if args.sin_sitios else [])
        + (["--dry-run"] if args.dry_run else []),
    ))

    print(f"Actualización diaria: {desde} -> {hasta}")
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

    print("\nActualización diaria terminada correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
