/* ============================================================
   Serie mensual vigente con nombres geográficos.
   Edita @anio y @variable según lo que quieras revisar.
   ============================================================ */

DECLARE @anio SMALLINT = 2025;
DECLARE @variable VARCHAR(20) = 'PREC';   -- PREC, TMAX, TMED, TMIN, EVAP

SELECT
    nom_ent,
    nom_mun,
    nom_loc,
    estacion_nombre,
    variable,
    anio,
    mes,
    valor,
    origen,
    estado,
    dias_con_dato,
    dias_esperados,
    completo,
    fecha_corte
FROM {{schema}}.vw_clima_mensual_geo
WHERE anio = @anio
  AND variable = @variable
ORDER BY nom_ent, nom_mun, estacion_nombre, mes;
