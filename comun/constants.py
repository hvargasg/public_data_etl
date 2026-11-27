"""Constantes de vigencia del modelo.

La ventana de datos que carga el ETL es 2023-01-01 a la fecha. No se almacena
el histórico anterior. Si en el futuro necesitas ampliar la ventana, cambia
estas constantes y vuelve a ejecutar las cargas.
"""

from datetime import date

DESDE_MINIMO = date(2023, 1, 1)
ANIO_MINIMO = 2023
MES_MINIMO = "2023-01"


def clamp_desde(value: date) -> date:
    """Devuelve la fecha, pero nunca antes de DESDE_MINIMO."""
    return max(value, DESDE_MINIMO)
