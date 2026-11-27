/* ============================================================
   Crea el schema datos_publicos dentro de DataLake si no existe.
   Ejecutar conectado a DataLake:
       sqlcmd -S servidor -d DataLake -i 00_crear_schema.sql

   El runner `python -m carga_inicial.run_inicial --init` hace esto
   automáticamente con el valor de DB_SCHEMA.
   ============================================================ */

SET NOCOUNT ON;
GO

IF SCHEMA_ID(N'datos_publicos') IS NULL
BEGIN
    EXEC(N'CREATE SCHEMA [datos_publicos] AUTHORIZATION [dbo]');
    PRINT 'Schema datos_publicos creado.';
END
ELSE
BEGIN
    PRINT 'El schema datos_publicos ya existe.';
END;
GO
