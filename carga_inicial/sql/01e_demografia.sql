/* ============================================================
   Base homologada - hechos demográficos, sociales y económicos
   Un indicador se guarda en el nivel donde se publica.
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID('{{schema}}.demografia_municipio', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.demografia_municipio (
        cvegeo       CHAR(5)       NOT NULL,
        anio         SMALLINT      NOT NULL,
        indicador_id SMALLINT      NOT NULL,
        valor        DECIMAL(18, 4) NULL,
        fuente_id    TINYINT       NOT NULL,
        fecha_carga  DATETIME2(0)  NOT NULL CONSTRAINT df_dem_mun_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_demografia_municipio PRIMARY KEY (cvegeo, anio, indicador_id, fuente_id),
        CONSTRAINT fk_dem_mun_municipio FOREIGN KEY (cvegeo)
            REFERENCES {{schema}}.municipio (cvegeo),
        CONSTRAINT fk_dem_mun_indicador FOREIGN KEY (indicador_id)
            REFERENCES {{schema}}.indicador (indicador_id),
        CONSTRAINT fk_dem_mun_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id),
        CONSTRAINT ck_dem_mun_anio CHECK (anio BETWEEN 1900 AND 2100)
    );
END;
GO

IF OBJECT_ID('{{schema}}.demografia_localidad', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.demografia_localidad (
        cve_loc      CHAR(9)       NOT NULL,
        anio         SMALLINT      NOT NULL,
        indicador_id SMALLINT      NOT NULL,
        valor        DECIMAL(18, 4) NULL,
        fuente_id    TINYINT       NOT NULL,
        fecha_carga  DATETIME2(0)  NOT NULL CONSTRAINT df_dem_loc_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_demografia_localidad PRIMARY KEY (cve_loc, anio, indicador_id, fuente_id),
        CONSTRAINT fk_dem_loc_localidad FOREIGN KEY (cve_loc)
            REFERENCES {{schema}}.localidad (cve_loc),
        CONSTRAINT fk_dem_loc_indicador FOREIGN KEY (indicador_id)
            REFERENCES {{schema}}.indicador (indicador_id),
        CONSTRAINT fk_dem_loc_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id),
        CONSTRAINT ck_dem_loc_anio CHECK (anio BETWEEN 1900 AND 2100)
    );
END;
GO

IF OBJECT_ID('{{schema}}.demografia_ageb', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.demografia_ageb (
        cve_ageb     VARCHAR(13)   NOT NULL,
        anio         SMALLINT      NOT NULL,
        indicador_id SMALLINT      NOT NULL,
        valor        DECIMAL(18, 4) NULL,
        fuente_id    TINYINT       NOT NULL,
        fecha_carga  DATETIME2(0)  NOT NULL CONSTRAINT df_dem_ageb_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_demografia_ageb PRIMARY KEY (cve_ageb, anio, indicador_id, fuente_id),
        CONSTRAINT fk_dem_ageb_ageb FOREIGN KEY (cve_ageb)
            REFERENCES {{schema}}.ageb (cve_ageb),
        CONSTRAINT fk_dem_ageb_indicador FOREIGN KEY (indicador_id)
            REFERENCES {{schema}}.indicador (indicador_id),
        CONSTRAINT fk_dem_ageb_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id),
        CONSTRAINT ck_dem_ageb_anio CHECK (anio BETWEEN 1900 AND 2100)
    );
END;
GO
