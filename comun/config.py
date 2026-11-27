"""Configuración del ETL. Las credenciales se leen del entorno, nunca del código."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def cargar_entorno() -> None:
    """Carga variables desde un archivo de entorno, si existe.

    - Desarrollo local: se busca un ``.env`` en la raíz del proyecto.
    - Docker con secretos montados: ``ETL_ENV_FILE`` indica la ruta del archivo.
    - Servidor de producción: los DAGs pasan los secretos de Infisical como
      variables de entorno del contenedor, así que no hay archivo que cargar.

    Las variables que ya existan en el entorno tienen prioridad.
    """
    try:  # opcional: permite cargar un .env local
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return

    ruta = os.getenv("ETL_ENV_FILE")
    if ruta:
        if not Path(ruta).is_file():
            raise RuntimeError(
                f"ETL_ENV_FILE apunta a un archivo inexistente: {ruta}"
            )
        load_dotenv(ruta, override=False)
    else:
        load_dotenv(override=False)


cargar_entorno()


def directorio_datos() -> Path:
    """Raíz de los datos locales. En Docker es el volumen montado en /app/data."""
    return Path(os.getenv("ETL_DATA_DIR", "data")).resolve()


@dataclass(frozen=True)
class Config:
    server: str = os.getenv("DB_SERVER", "")
    database: str = os.getenv("DB_NAME", "DataLake")
    user: str = os.getenv("DB_USER", "")
    password: str = os.getenv("DB_PASSWORD", "")
    driver: str = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    schema: str = os.getenv("DB_SCHEMA", "datos_publicos")
    encrypt: str = os.getenv("DB_ENCRYPT", "yes")
    trust_cert: str = os.getenv("DB_TRUST_CERT", "yes")

    def validate(self) -> None:
        missing = [
            name
            for name, value in {
                "DB_SERVER": self.server,
                "DB_USER": self.user,
                "DB_PASSWORD": self.password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Faltan variables de entorno: "
                + ", ".join(missing)
                + ". Copia .env.example a .env y complétalo "
                "(o revisa los secretos de Infisical en producción)."
            )
