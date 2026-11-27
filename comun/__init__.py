"""Infraestructura compartida: configuración, conexión y utilidades.

No contiene lógica de negocio. La usan tanto `carga_inicial` como
`actualizacion` para no duplicar la conexión a SQL Server.
"""

__all__ = ["config", "constants", "db", "utils"]
