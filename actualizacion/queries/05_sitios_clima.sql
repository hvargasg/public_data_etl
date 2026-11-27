/* ============================================================
   Clima mensual derivado de los sitios.
   Muestra NEAREST e IDW lado a lado para comparar.
   ============================================================ */

DECLARE @anio SMALLINT = 2025;
DECLARE @mes TINYINT = 1;
DECLARE @variable VARCHAR(20) = 'PREC';

SELECT
    s.codigo_sitio,
    s.nombre AS sitio,
    v.codigo AS variable,
    c.anio,
    c.mes,
    MAX(CASE WHEN c.metodo = 'NEAREST' THEN c.valor END) AS nearest,
    MAX(CASE WHEN c.metodo = 'IDW' THEN c.valor END) AS idw,
    MAX(CASE WHEN c.metodo = 'IDW' THEN c.n_estaciones END) AS estaciones_idw
FROM {{schema}}.clima_sitio_mensual c
JOIN {{schema}}.sitio s ON s.sitio_id = c.sitio_id
JOIN {{schema}}.variable v ON v.variable_id = c.variable_id
WHERE c.anio = @anio
  AND c.mes = @mes
  AND v.codigo = @variable
GROUP BY s.codigo_sitio, s.nombre, v.codigo, c.anio, c.mes
ORDER BY s.codigo_sitio;
