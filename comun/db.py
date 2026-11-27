"""Utilidades de conexión, ejecución de SQL y carga masiva."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL

from .config import Config

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_database(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(
            f"Nombre de base de datos no válido: {name!r}. "
            "Usa letras, números y guion bajo, empezando por letra o guion bajo."
        )
    return name


def get_engine(cfg: Config | None = None, database: str | None = None) -> Engine:
    cfg = cfg or Config()
    cfg.validate()
    db = _check_database(database or cfg.database)
    url = URL.create(
        "mssql+pyodbc",
        username=cfg.user,
        password=cfg.password,
        host=cfg.server,
        database=db,
        query={
            "driver": cfg.driver,
            "Encrypt": cfg.encrypt,
            "TrustServerCertificate": cfg.trust_cert,
            "ConnectionTimeout": "120",
        },
    )
    return create_engine(url, fast_executemany=True, pool_pre_ping=True)


def _check_schema(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(
            f"Nombre de schema no válido: {name!r}. "
            "Usa letras, números y guion bajo, empezando por letra o guion bajo."
        )
    return name


def render_sql(sql: str, schema: str | None = None) -> str:
    """Reemplaza el token {{schema}} por el schema configurado."""
    cfg = Config()
    target = _check_schema(schema or cfg.schema)
    return sql.replace("{{schema}}", target)


def create_schema(cfg: Config | None = None) -> str:
    """Crea el schema configurado en DB_SCHEMA si no existe."""
    cfg = cfg or Config()
    cfg.validate()
    schema = _check_schema(cfg.schema)
    engine = get_engine(cfg)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "IF SCHEMA_ID(N'{0}') IS NULL "
                "EXEC(N'CREATE SCHEMA [{0}] AUTHORIZATION [dbo]');".format(schema)
            )
    finally:
        engine.dispose()
    return schema


def create_database(cfg: Config | None = None) -> str:
    """Crea la base configurada en DB_NAME si no existe.

    Se conecta a `master` en modo AUTOCOMMIT porque `CREATE DATABASE` no puede
    ejecutarse dentro de una transacción de usuario. Devuelve el nombre usado.
    """
    cfg = cfg or Config()
    cfg.validate()
    db = _check_database(cfg.database)
    engine = get_engine(cfg, database="master")
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(
                f"IF DB_ID(N'{db}') IS NULL CREATE DATABASE [{db}];"
            )
    finally:
        engine.dispose()
    return db


def split_batches(sql: str) -> Iterator[str]:
    """Divide un script por líneas que sean exactamente GO."""
    batch: list[str] = []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            if batch:
                yield "\n".join(batch)
                batch = []
        else:
            batch.append(line)
    if batch:
        yield "\n".join(batch)


def exec_sql_file(engine: Engine, path: str | Path, schema: str | None = None) -> None:
    sql = render_sql(Path(path).read_text(encoding="utf-8"), schema)
    with engine.begin() as conn:
        for batch in split_batches(sql):
            if batch.strip():
                conn.exec_driver_sql(batch)


def read_sql(engine: Engine, sql: str, params: dict | None = None) -> pd.DataFrame:
    sql = render_sql(sql)
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def _check_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Identificador no válido: {name!r}")
    return name


def upsert(
    engine: Engine,
    df: pd.DataFrame,
    table: str,
    key_cols: Sequence[str],
    schema: str | None = None,
) -> int:
    """MERGE genérico para tablas sin columnas GEOGRAPHY.

    Usa una tabla de staging real y MERGE. Para tablas con geometría usa
    insert_rows() con la conversión explícita a geography.
    """
    if df.empty:
        return 0

    table = _check_ident(table)
    schema = _check_ident(schema or Config().schema)
    cols = [_check_ident(c) for c in df.columns]
    keys = [_check_ident(k) for k in key_cols]
    missing = [k for k in keys if k not in cols]
    if missing:
        raise ValueError(f"Faltan columnas clave en {table}: {missing}")

    stage = f"_stage_{table}"
    set_cols = [c for c in cols if c not in keys]
    on_clause = " AND ".join(f"t.[{c}] = s.[{c}]" for c in keys)
    insert_cols = ", ".join(f"[{c}]" for c in cols)
    insert_vals = ", ".join(f"s.[{c}]" for c in cols)

    when_matched = ""
    if set_cols:
        set_clause = ", ".join(f"t.[{c}] = s.[{c}]" for c in set_cols)
        when_matched = f"WHEN MATCHED THEN UPDATE SET {set_clause}"

    merge_sql = f"""
        MERGE [{schema}].[{table}] AS t
        USING [{schema}].[{stage}] AS s
        ON {on_clause}
        {when_matched}
        WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});
        DROP TABLE [{schema}].[{stage}];
    """

    with engine.begin() as conn:
        df.to_sql(stage, conn, schema=schema, if_exists="replace", index=False, chunksize=1000)
        conn.exec_driver_sql(merge_sql)
    return len(df)


def insert_rows(
    engine: Engine,
    sql: str,
    rows: Iterable[Sequence],
    chunksize: int = 500,
) -> int:
    """executemany con la sentencia SQL indicada (para geography, etc.)."""
    rows = list(rows)
    if not rows:
        return 0
    sql = render_sql(sql)
    with engine.begin() as conn:
        for start in range(0, len(rows), chunksize):
            conn.exec_driver_sql(sql, rows[start : start + chunksize])
    return len(rows)


def get_fuente_id(engine: Engine, codigo: str) -> int:
    sql = render_sql("SELECT fuente_id FROM {{schema}}.fuente WHERE codigo = :codigo")
    with engine.connect() as conn:
        value = conn.execute(text(sql), {"codigo": codigo}).scalar_one_or_none()
    if value is None:
        raise RuntimeError(f"No existe la fuente {codigo!r} en el catálogo de fuentes")
    return int(value)


def get_variable_map(engine: Engine) -> dict[str, int]:
    sql = render_sql("SELECT codigo, variable_id FROM {{schema}}.variable")
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).all()
    return {codigo: int(vid) for codigo, vid in rows}


@contextmanager
def log_carga(engine: Engine, proceso: str, fuente_codigo: str | None = None):
    """Registra una corrida en el schema configurado."""
    fuente_id = None
    if fuente_codigo:
        try:
            fuente_id = get_fuente_id(engine, fuente_codigo)
        except RuntimeError:
            fuente_id = None

    sql_insert = render_sql(
        """
        INSERT INTO {{schema}}.carga_log (proceso, fuente_id)
        OUTPUT INSERTED.carga_id
        VALUES (:proceso, :fuente_id)
        """
    )
    with engine.begin() as conn:
        carga_id = conn.execute(
            text(sql_insert),
            {"proceso": proceso, "fuente_id": fuente_id},
        ).scalar_one()

    info = {"filas": 0, "mensaje": None}
    estado = "OK"
    try:
        yield info
    except Exception as exc:  # noqa: BLE001
        estado = "ERROR"
        info["mensaje"] = str(exc)[:1000]
        raise
    finally:
        sql_update = render_sql(
            """
            UPDATE {{schema}}.carga_log
            SET fin = SYSUTCDATETIME(), filas = :filas,
                estado = :estado, mensaje = :mensaje
            WHERE carga_id = :carga_id
            """
        )
        with engine.begin() as conn:
            conn.execute(
                text(sql_update),
                {
                    "filas": info["filas"],
                    "estado": estado,
                    "mensaje": info["mensaje"],
                    "carga_id": carga_id,
                },
            )
