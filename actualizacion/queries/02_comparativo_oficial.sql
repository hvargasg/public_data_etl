/* ============================================================
   Comparativo: serie propia (CALCULADO) vs oficial (OFICIAL).
   Sirve como control de calidad mensual.
   ============================================================ */

DECLARE @anio SMALLINT = 2025;

SELECT
    c.estacion_id,
    e.clave_smn,
    e.nombre AS estacion,
    c.variable_id,
    v.codigo AS variable,
    c.anio,
    c.mes,
    c.valor AS calculado,
    o.valor AS oficial,
    c.valor - o.valor AS diferencia,
    c.dias_con_dato,
    c.dias_esperados,
    c.completo
FROM {{schema}}.clima_mensual c
JOIN {{schema}}.clima_mensual o
  ON o.estacion_id = c.estacion_id
 AND o.variable_id = c.variable_id
 AND o.anio = c.anio
 AND o.mes = c.mes
JOIN {{schema}}.estacion e ON e.estacion_id = c.estacion_id
JOIN {{schema}}.variable v ON v.variable_id = c.variable_id
WHERE c.origen = 'CALCULADO'
  AND o.origen = 'OFICIAL'
  AND c.anio = @anio
ORDER BY ABS(c.valor - o.valor) DESC;
