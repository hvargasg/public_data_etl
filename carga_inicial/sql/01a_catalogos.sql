/* ============================================================
   Base de datos pública - catálogos base
   Esquema: {{schema}} (DB_SCHEMA) | Sin prefijo
   Motor: SQL Server 2016+
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

/* Variables climáticas y su forma de agregación diaria -> mensual */
IF OBJECT_ID('{{schema}}.variable', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.variable (
        variable_id TINYINT       NOT NULL CONSTRAINT pk_variable PRIMARY KEY,
        codigo      VARCHAR(20)   NOT NULL CONSTRAINT uq_variable_codigo UNIQUE,
        nombre      NVARCHAR(100) NOT NULL,
        unidad      NVARCHAR(10)  NOT NULL,
        escala      VARCHAR(10)   NOT NULL,
        agregacion  VARCHAR(10)   NOT NULL,
        descripcion NVARCHAR(300) NULL,
        CONSTRAINT ck_variable_escala CHECK (escala IN ('DIARIA', 'MENSUAL')),
        CONSTRAINT ck_variable_agregacion CHECK (agregacion IN ('SUMA', 'MEDIA'))
    );
END;
GO

/* Fuentes de datos y su frecuencia de actualización */
IF OBJECT_ID('{{schema}}.fuente', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.fuente (
        fuente_id     TINYINT        NOT NULL CONSTRAINT pk_fuente PRIMARY KEY,
        codigo        VARCHAR(40)    NOT NULL CONSTRAINT uq_fuente_codigo UNIQUE,
        nombre        NVARCHAR(200)  NOT NULL,
        url_patron    NVARCHAR(500)  NULL,
        frecuencia    VARCHAR(30)    NULL,
        fecha_emision DATE           NULL,
        licencia      NVARCHAR(200)  NULL,
        notas         NVARCHAR(1000) NULL
    );
END;
GO

/* Indicadores demográficos, sociales y económicos */
IF OBJECT_ID('{{schema}}.indicador', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.indicador (
        indicador_id SMALLINT      NOT NULL CONSTRAINT pk_indicador PRIMARY KEY,
        dominio      VARCHAR(20)   NOT NULL,
        codigo       VARCHAR(40)   NOT NULL CONSTRAINT uq_indicador_codigo UNIQUE,
        nombre       NVARCHAR(200) NOT NULL,
        unidad       NVARCHAR(20)  NULL,
        niveles      NVARCHAR(50)  NULL,   -- MUN,LOC,AGEB
        descripcion  NVARCHAR(500) NULL,
        CONSTRAINT ck_indicador_dominio CHECK (dominio IN ('DEMO', 'SOCIO', 'ECON'))
    );
END;
GO

/* Bitácora de ejecuciones ETL */
IF OBJECT_ID('{{schema}}.carga_log', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.carga_log (
        carga_id  BIGINT        IDENTITY CONSTRAINT pk_carga_log PRIMARY KEY,
        proceso   VARCHAR(50)   NOT NULL,
        fuente_id TINYINT       NULL,
        inicio    DATETIME2(0)  NOT NULL CONSTRAINT df_carga_log_inicio DEFAULT SYSUTCDATETIME(),
        fin       DATETIME2(0)  NULL,
        filas     INT           NULL,
        estado    VARCHAR(20)   NOT NULL CONSTRAINT df_carga_log_estado DEFAULT 'EN_PROCESO',
        mensaje   NVARCHAR(1000) NULL,
        CONSTRAINT fk_carga_log_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id)
    );
END;
GO
