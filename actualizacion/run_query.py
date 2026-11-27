"""Ejecuta una query de control y muestra el resultado en consola.

Uso:
    python -m actualizacion.run_query --archivo actualizacion/queries/02_comparativo_oficial.sql
    python -m actualizacion.run_query --archivo actualizacion/queries/03_cobertura.sql --limite 50
"""

from __future__ import annotations

import argparse
from pathlib import Path

from comun.db import get_engine, read_sql, render_sql


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecuta una query SQL de control.")
    parser.add_argument("--archivo", required=True)
    parser.add_argument("--limite", type=int, default=200)
    parser.add_argument(
        "--ejecutar",
        action="store_true",
        help="Ejecuta el archivo como DML/DDL y hace commit (no imprime filas).",
    )
    args = parser.parse_args()

    path = Path(args.archivo)
    if not path.exists():
        raise SystemExit(f"No existe {path}")

    sql = render_sql(path.read_text(encoding="utf-8"))
    engine = get_engine()

    if args.ejecutar:
        with engine.begin() as conn:
            result = conn.exec_driver_sql(sql)
        print(f"Ejecutado. Filas afectadas: {result.rowcount}")
        return 0

    df = read_sql(engine, sql)

    if df.empty:
        print("La query no devolvió filas.")
        return 0

    print(df.head(args.limite).to_string(index=False))
    if len(df) > args.limite:
        print(f"\n... {len(df) - args.limite:,} filas más (usa --limite para ver más).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
