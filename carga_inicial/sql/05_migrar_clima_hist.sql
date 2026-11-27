/* ============================================================
   Migración de la tabla histórica dbo.clima_hist al modelo nuevo.
   Es idempotente: no duplica filas ya migradas.
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID('dbo.clima_hist', 'U') IS NOT NULL
BEGIN
    INSERT INTO {{schema}}.clima_estatal_mensual
        (cve_ent, variable_id, anio, mes, valor, fuente_id)
    SELECT DISTINCT
           e.cve_ent,
           v.variable_id,
           c.[Año],
           c.Mes,
           x.valor,
           f.fuente_id
    FROM dbo.clima_hist c
    JOIN (VALUES
        (N'Aguascalientes', '01'),
        (N'Baja California', '02'),
        (N'Baja California Sur', '03'),
        (N'Campeche', '04'),
        (N'Coahuila', '05'), (N'Coahuila de Zaragoza', '05'),
        (N'Colima', '06'),
        (N'Chiapas', '07'),
        (N'Chihuahua', '08'),
        (N'Ciudad de México', '09'), (N'Distrito Federal', '09'), (N'CDMX', '09'),
        (N'Durango', '10'),
        (N'Guanajuato', '11'),
        (N'Guerrero', '12'),
        (N'Hidalgo', '13'),
        (N'Jalisco', '14'),
        (N'Estado de México', '15'), (N'México', '15'),
        (N'Michoacán', '16'), (N'Michoacán de Ocampo', '16'),
        (N'Morelos', '17'),
        (N'Nayarit', '18'),
        (N'Nuevo León', '19'),
        (N'Oaxaca', '20'),
        (N'Puebla', '21'),
        (N'Querétaro', '22'), (N'Querétaro de Arteaga', '22'),
        (N'Quintana Roo', '23'),
        (N'San Luis Potosí', '24'),
        (N'Sinaloa', '25'),
        (N'Sonora', '26'),
        (N'Tabasco', '27'),
        (N'Tamaulipas', '28'),
        (N'Tlaxcala', '29'),
        (N'Veracruz', '30'), (N'Veracruz de Ignacio de la Llave', '30'),
        (N'Yucatán', '31'),
        (N'Zacatecas', '32')
    ) AS e(nom_ent, cve_ent)
      ON e.nom_ent = c.Estado
    CROSS APPLY (VALUES
    ('PREC', c.Precipitacion),
    ('TMAX', c.Tmax),
    ('TMED', c.Tmed),
    ('TMIN', c.Tmin)
) AS x(codigo, valor)
JOIN {{schema}}.variable v ON v.codigo = x.codigo
JOIN {{schema}}.fuente  f ON f.codigo = 'PDF_ESTATAL'
WHERE c.Estado <> 'Nacional'
  AND c.[Año] IS NOT NULL
  AND c.[Año] >= 2023
  AND c.Mes BETWEEN 1 AND 12
  AND x.valor IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM {{schema}}.clima_estatal_mensual h
      WHERE h.cve_ent = e.cve_ent
        AND h.variable_id = v.variable_id
        AND h.anio = c.[Año]
        AND h.mes = c.Mes
        AND h.fuente_id = f.fuente_id
  );
END;
GO

SELECT 'filas migradas' AS concepto, COUNT(*) AS total
FROM {{schema}}.clima_estatal_mensual
WHERE fuente_id = (SELECT fuente_id FROM {{schema}}.fuente WHERE codigo = 'PDF_ESTATAL');
GO
