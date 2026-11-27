/* ============================================================
   Purga de datos climáticos anteriores a 2023-01-01.
   La ventana vigente del modelo es 2023 a la fecha.

   Uso recomendado (sustituye {{schema}} automáticamente):
       python -m carga_inicial.run_inicial --purgar

   Si lo ejecutas manualmente con sqlcmd, reemplaza {{schema}} por
   datos_publicos y conéctate a DataLake:
       sqlcmd -S servidor -d DataLake -i 06_purgar_antes_2023.sql

   Es destructivo. Haz respaldo antes de ejecutarlo.
   No borra demografía: el Censo 2020 sigue siendo la edición vigente.
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID('{{schema}}.clima_diario', 'U') IS NULL
BEGIN
    PRINT 'Las tablas clima_* no existen; se omite la purga.';
END
ELSE
BEGIN
    BEGIN TRANSACTION;

    DELETE FROM {{schema}}.clima_sitio_mensual
    WHERE anio < 2023;

    DELETE FROM {{schema}}.clima_mensual
    WHERE anio < 2023;

    DELETE FROM {{schema}}.clima_diario
    WHERE fecha < '2023-01-01';

    DELETE FROM {{schema}}.clima_estatal_mensual
    WHERE anio < 2023;

    COMMIT TRANSACTION;

    SELECT 'clima_sitio_mensual' AS tabla, COUNT(*) AS filas_restantes
    FROM {{schema}}.clima_sitio_mensual
    UNION ALL
    SELECT 'clima_mensual', COUNT(*) FROM {{schema}}.clima_mensual
    UNION ALL
    SELECT 'clima_diario', COUNT(*) FROM {{schema}}.clima_diario
    UNION ALL
    SELECT 'clima_estatal_mensual', COUNT(*) FROM {{schema}}.clima_estatal_mensual;
END
GO
