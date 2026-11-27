/* ============================================================
   Base homologada - geografía oficial (INEGI Marco Geoestadístico)
   Jerarquía: entidad -> municipio -> localidad -> AGEB
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID('{{schema}}.entidad', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.entidad (
        cve_ent    CHAR(2)       NOT NULL CONSTRAINT pk_entidad PRIMARY KEY,
        nom_ent    NVARCHAR(100) NOT NULL,
        version_mg CHAR(4)       NOT NULL,
        geom       GEOGRAPHY     NOT NULL
    );
END;
GO

IF OBJECT_ID('{{schema}}.municipio', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.municipio (
        cvegeo     CHAR(5)       NOT NULL CONSTRAINT pk_municipio PRIMARY KEY,
        cve_ent    CHAR(2)       NOT NULL,
        cve_mun    CHAR(3)       NOT NULL,
        nom_mun    NVARCHAR(150) NOT NULL,
        version_mg CHAR(4)       NOT NULL,
        geom       GEOGRAPHY     NOT NULL,
        CONSTRAINT fk_municipio_entidad FOREIGN KEY (cve_ent)
            REFERENCES {{schema}}.entidad (cve_ent),
        CONSTRAINT uq_municipio UNIQUE (cve_ent, cve_mun)
    );
END;
GO

IF OBJECT_ID('{{schema}}.localidad', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.localidad (
        cve_loc       CHAR(9)       NOT NULL CONSTRAINT pk_localidad PRIMARY KEY,
        cvegeo        CHAR(5)       NOT NULL,
        cve_loc_inegi CHAR(4)       NOT NULL,
        nom_loc       NVARCHAR(200) NOT NULL,
        ambito        VARCHAR(10)   NULL,
        version_mg    CHAR(4)       NOT NULL,
        geom          GEOGRAPHY     NOT NULL,
        CONSTRAINT fk_localidad_municipio FOREIGN KEY (cvegeo)
            REFERENCES {{schema}}.municipio (cvegeo),
        CONSTRAINT uq_localidad UNIQUE (cvegeo, cve_loc_inegi),
        CONSTRAINT ck_localidad_ambito CHECK (ambito IS NULL OR ambito IN ('URBANA', 'RURAL'))
    );
END;
GO

IF OBJECT_ID('{{schema}}.ageb', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.ageb (
        cve_ageb       VARCHAR(13) NOT NULL CONSTRAINT pk_ageb PRIMARY KEY,
        cve_loc        CHAR(9)     NULL,
        cvegeo         CHAR(5)     NOT NULL,
        cve_ageb_inegi VARCHAR(4)  NOT NULL,
        tipo           VARCHAR(10) NULL,
        version_mg     CHAR(4)     NOT NULL,
        geom           GEOGRAPHY   NOT NULL,
        CONSTRAINT fk_ageb_localidad FOREIGN KEY (cve_loc)
            REFERENCES {{schema}}.localidad (cve_loc),
        CONSTRAINT fk_ageb_municipio FOREIGN KEY (cvegeo)
            REFERENCES {{schema}}.municipio (cvegeo),
        CONSTRAINT uq_ageb UNIQUE (cvegeo, cve_loc, cve_ageb_inegi),
        CONSTRAINT ck_ageb_tipo CHECK (tipo IS NULL OR tipo IN ('URBANA', 'RURAL')),
        CONSTRAINT ck_ageb_largo CHECK (LEN(cve_ageb) IN (9, 13)),
        CONSTRAINT ck_ageb_geo CHECK (LEFT(cve_ageb, 5) = cvegeo),
        CONSTRAINT ck_ageb_loc CHECK (
            LEN(cve_ageb) = 9 OR cve_loc IS NULL OR LEFT(cve_ageb, 9) = cve_loc
        )
    );
END;
GO
