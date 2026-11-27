/* ============================================================
   Chequeos de calidad en una sola tabla.
   Cualquier valor distinto de 0 en "total" requiere revisión,
   salvo los que se marcan como informativos.
   ============================================================ */

SELECT 'estaciones_sin_municipio' AS chequeo, COUNT(*) AS total
FROM {{schema}}.estacion
WHERE cvegeo IS NULL

UNION ALL

SELECT 'sitios_sin_localidad', COUNT(*)
FROM {{schema}}.sitio
WHERE cve_loc IS NULL

UNION ALL

SELECT 'meses_calculados_incompletos', COUNT(*)
FROM {{schema}}.clima_mensual
WHERE origen = 'CALCULADO' AND completo = 0

UNION ALL

SELECT 'duplicados_en_vista_vigente', COUNT(*)
FROM (
    SELECT estacion_id, variable_id, anio, mes
    FROM {{schema}}.vw_clima_mensual_vigente
    GROUP BY estacion_id, variable_id, anio, mes
    HAVING COUNT(*) > 1
) x

UNION ALL

SELECT 'estaciones_sin_datos_diarios', COUNT(*)
FROM {{schema}}.estacion e
WHERE NOT EXISTS (
    SELECT 1 FROM {{schema}}.clima_diario d
    WHERE d.estacion_id = e.estacion_id
)

UNION ALL

SELECT 'oficial_sin_calculado', COUNT(*)
FROM {{schema}}.clima_mensual o
WHERE o.origen = 'OFICIAL'
  AND NOT EXISTS (
      SELECT 1 FROM {{schema}}.clima_mensual c
      WHERE c.estacion_id = o.estacion_id
        AND c.variable_id = o.variable_id
        AND c.anio = o.anio
        AND c.mes = o.mes
        AND c.origen = 'CALCULADO'
  );
