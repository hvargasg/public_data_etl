-- Columnas de enlace geográfico oficial (INEGI) para las tablas de negocio.
-- Son idempotentes: el ETL las crea la primera vez y después no hace nada.
-- cvegeo = clave de municipio (5 dígitos, incluye el estado en los primeros 2).
-- cve_ent = clave de estado (2 dígitos).

IF COL_LENGTH('dbo.Clientes', 'cvegeo') IS NULL
    ALTER TABLE dbo.Clientes ADD cvegeo CHAR(5) NULL;
GO

IF COL_LENGTH('dbo.Clientes', 'cve_ent') IS NULL
    ALTER TABLE dbo.Clientes ADD cve_ent CHAR(2) NULL;
GO

IF COL_LENGTH('dbo.CEDIS', 'cvegeo') IS NULL
    ALTER TABLE dbo.CEDIS ADD cvegeo CHAR(5) NULL;
GO

IF COL_LENGTH('dbo.CEDIS', 'cve_ent') IS NULL
    ALTER TABLE dbo.CEDIS ADD cve_ent CHAR(2) NULL;
GO
