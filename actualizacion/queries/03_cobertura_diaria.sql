/* ============================================================
   Cobertura diaria por estación, variable y año.
   Ordena primero las estaciones con menos días para detectar huecos.
   ============================================================ */

DECLARE @desde DATE = '2023-01-01';
DECLARE @hasta DATE = '2025-12-31';

SELECT
    e.clave_smn,
    e.nombre AS estacion,
    v.codigo AS variable,
    YEAR(d.fecha) AS anio,
    COUNT(*) AS dias_con_dato,
    MIN(d.fecha) AS primer_dia,
    MAX(d.fecha) AS ultimo_dia
FROM {{schema}}.clima_diario d
JOIN {{schema}}.estacion e ON e.estacion_id = d.estacion_id
JOIN {{schema}}.variable v ON v.variable_id = d.variable_id
WHERE d.fecha BETWEEN @desde AND @hasta
  AND d.valor IS NOT NULL
GROUP BY e.clave_smn, e.nombre, v.codigo, YEAR(d.fecha)
ORDER BY anio DESC, dias_con_dato ASC;
