/* ============================================================
   Crea la base de datos DataLake si no existe.
   Ejecutar conectado a master, por ejemplo:
       sqlcmd -S servidor -d master -i 00_crear_base.sql

   El runner `python -m carga_inicial.run_inicial --init` hace esto
   automáticamente con el nombre configurado en DB_NAME. Este archivo es el
   respaldo manual para crear la base por defecto.
   ============================================================ */

SET NOCOUNT ON;
GO

IF DB_ID(N'DataLake') IS NULL
BEGIN
    CREATE DATABASE [DataLake];
    PRINT 'Base de datos DataLake creada.';
END
ELSE
BEGIN
    PRINT 'La base de datos DataLake ya existe.';
END;
GO
