-- Serie estatal mensual: prioridad de fuentes y compatibilidad con
-- dbo.clima_hist.
--
-- Fuente operativa: SMN_RED_CSV (red reducida, estación-mes agregada por
-- entidad). Fuente legacy/opcional: PDF_ESTATAL (tabla estado-mes del PDF).
-- La vista vigente prefiere el CSV y usa el PDF solo para meses sin CSV.
--
-- Es idempotente: el ETL crea/actualiza las vistas en cada corrida.

SET NOCOUNT ON;
GO

/* Serie estatal vigente: una fila por entidad, variable, año y mes. */
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

/* Compatibilidad con dbo.clima_hist (formato ancho). Usa la serie vigente. */
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
