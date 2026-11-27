/* ============================================================
   Base homologada - vistas de consulta
   ============================================================ */

SET NOCOUNT ON;
GO

/* Mensual "vigente": si existe OFICIAL, gana; si no, CALCULADO. */
CREATE OR ALTER VIEW {{schema}}.vw_clima_mensual_vigente
AS
WITH ranked AS (
    SELECT m.*,
           ROW_NUMBER() OVER (
               PARTITION BY m.estacion_id, m.variable_id, m.anio, m.mes
               ORDER BY CASE WHEN m.origen = 'OFICIAL' THEN 0 ELSE 1 END,
                        m.fecha_carga DESC
           ) AS rn
    FROM {{schema}}.clima_mensual m
)
SELECT estacion_id, variable_id, anio, mes, valor, origen, estado, fuente_id,
       dias_con_dato, dias_esperados, completo, fecha_corte, fecha_carga
FROM ranked
WHERE rn = 1;
GO

/* Mensual con nombres geográficos de la estación. */
CREATE OR ALTER VIEW {{schema}}.vw_clima_mensual_geo
AS
SELECT v.estacion_id, e.clave_smn, e.clave_sih, e.nombre AS estacion_nombre,
       e.cve_ent, en.nom_ent, e.cvegeo, mu.nom_mun,
       e.cve_loc, lo.nom_loc,
       v.variable_id, var.codigo AS variable, var.unidad,
       v.anio, v.mes, v.valor, v.origen, v.estado,
       v.dias_con_dato, v.dias_esperados, v.completo, v.fecha_corte
FROM {{schema}}.vw_clima_mensual_vigente v
JOIN {{schema}}.estacion e   ON e.estacion_id = v.estacion_id
JOIN {{schema}}.variable var ON var.variable_id = v.variable_id
LEFT JOIN {{schema}}.entidad en   ON en.cve_ent = e.cve_ent
LEFT JOIN {{schema}}.municipio mu ON mu.cvegeo = e.cvegeo
LEFT JOIN {{schema}}.localidad lo ON lo.cve_loc = e.cve_loc;
GO

/* Sitios con su geografía oficial homologada. */
CREATE OR ALTER VIEW {{schema}}.vw_sitio_geografia
AS
SELECT s.sitio_id, s.codigo_sitio, s.nombre, s.lat, s.lon, s.altitud_m,
       s.cve_ent, en.nom_ent,
       s.cvegeo, mu.nom_mun,
       s.cve_loc, lo.nom_loc, lo.ambito,
       s.cve_ageb, a.tipo AS ageb_tipo,
       s.metodo_asignacion, s.en_limite, s.sin_localidad
FROM {{schema}}.sitio s
LEFT JOIN {{schema}}.entidad en   ON en.cve_ent = s.cve_ent
LEFT JOIN {{schema}}.municipio mu ON mu.cvegeo = s.cvegeo
LEFT JOIN {{schema}}.localidad lo ON lo.cve_loc = s.cve_loc
LEFT JOIN {{schema}}.ageb a       ON a.cve_ageb = s.cve_ageb;
GO

/* Clima mensual de cada sitio contra sus k estaciones vecinas. */
CREATE OR ALTER VIEW {{schema}}.vw_sitio_clima_mensual
AS
SELECT s.sitio_id, s.codigo_sitio,
       se.ranking, se.distancia_km, se.peso_idw,
       e.estacion_id, e.clave_smn, e.clave_sih, e.nombre AS estacion_nombre,
       v.variable_id, var.codigo AS variable, var.unidad,
       v.anio, v.mes, v.valor, v.origen, v.estado,
       v.completo, v.dias_con_dato, v.dias_esperados
FROM {{schema}}.sitio s
JOIN {{schema}}.sitio_estacion se ON se.sitio_id = s.sitio_id
JOIN {{schema}}.estacion e        ON e.estacion_id = se.estacion_id
JOIN {{schema}}.vw_clima_mensual_vigente v ON v.estacion_id = e.estacion_id
JOIN {{schema}}.variable var      ON var.variable_id = v.variable_id;
GO

/* Solo la estación más cercana (ranking = 1). */
CREATE OR ALTER VIEW {{schema}}.vw_sitio_clima_cercano
AS
SELECT *
FROM {{schema}}.vw_sitio_clima_mensual
WHERE ranking = 1;
GO

/* Serie estatal vigente: prioriza la red reducida (SMN_RED_CSV) sobre el PDF. */
CREATE OR ALTER VIEW {{schema}}.vw_clima_estatal_vigente
AS
WITH ranked AS (
    SELECT h.cve_ent, h.variable_id, h.anio, h.mes, h.valor,
           h.fuente_id, f.codigo AS fuente, h.fecha_carga,
           ROW_NUMBER() OVER (
               PARTITION BY h.cve_ent, h.variable_id, h.anio, h.mes
               ORDER BY CASE f.codigo
                            WHEN 'SMN_RED_CSV' THEN 0
                            WHEN 'PDF_ESTATAL' THEN 1
                            ELSE 9
                        END,
                        h.fecha_carga DESC
           ) AS rn
    FROM {{schema}}.clima_estatal_mensual h
    JOIN {{schema}}.fuente f ON f.fuente_id = h.fuente_id
)
SELECT cve_ent, variable_id, anio, mes, valor,
       fuente_id, fuente, fecha_carga
FROM ranked
WHERE rn = 1;
GO

/* Compatibilidad con la tabla histórica dbo.clima_hist (formato ancho). */
CREATE OR ALTER VIEW {{schema}}.vw_clima_hist_compat
AS
SELECT DATEFROMPARTS(h.anio, h.mes, 1) AS FECHA,
       en.nom_ent AS Estado,
       h.anio AS [Año],
       h.mes AS Mes,
       MAX(CASE WHEN v.codigo = 'PREC' THEN h.valor END) AS Precipitacion,
       MAX(CASE WHEN v.codigo = 'TMAX' THEN h.valor END) AS Tmax,
       MAX(CASE WHEN v.codigo = 'TMED' THEN h.valor END) AS Tmed,
       MAX(CASE WHEN v.codigo = 'TMIN' THEN h.valor END) AS Tmin,
       ROUND(MAX(CASE WHEN v.codigo = 'TMAX' THEN h.valor END)
             - MAX(CASE WHEN v.codigo = 'TMIN' THEN h.valor END), 2) AS Tdiff
FROM {{schema}}.vw_clima_estatal_vigente h
JOIN {{schema}}.entidad en   ON en.cve_ent = h.cve_ent
JOIN {{schema}}.variable v   ON v.variable_id = h.variable_id
GROUP BY h.anio, h.mes, en.nom_ent;
GO
