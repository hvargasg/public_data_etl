/* ============================================================
   Base homologada - estaciones climáticas y sitios de interés
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID('{{schema}}.estacion', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.estacion (
        estacion_id    INT IDENTITY CONSTRAINT pk_estacion PRIMARY KEY,
        clave_smn      VARCHAR(10)   NULL,
        clave_sih      VARCHAR(20)   NULL,
        nombre         NVARCHAR(200) NOT NULL,
        lat            DECIMAL(9, 6) NOT NULL,
        lon            DECIMAL(9, 6) NOT NULL,
        geom           GEOGRAPHY     NOT NULL,
        altitud_m      DECIMAL(7, 1) NULL,
        cve_ent        CHAR(2)       NULL,
        cvegeo         CHAR(5)       NULL,
        cve_loc        CHAR(9)       NULL,
        cve_ageb       VARCHAR(13)   NULL,
        situacion      VARCHAR(20)   NULL,
        tipo           NVARCHAR(50)  NULL,
        organismo      NVARCHAR(100) NULL,
        cuenca         NVARCHAR(150) NULL,
        inicio         DATE          NULL,
        mas_reciente   DATE          NULL,
        url_mensual    NVARCHAR(400) NULL,
        url_diario     NVARCHAR(400) NULL,
        url_extremos   NVARCHAR(400) NULL,
        version_indice VARCHAR(20)   NULL,
        fecha_carga    DATETIME2(0)  NOT NULL CONSTRAINT df_estacion_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT fk_estacion_entidad FOREIGN KEY (cve_ent)
            REFERENCES {{schema}}.entidad (cve_ent),
        CONSTRAINT fk_estacion_municipio FOREIGN KEY (cvegeo)
            REFERENCES {{schema}}.municipio (cvegeo),
        CONSTRAINT fk_estacion_localidad FOREIGN KEY (cve_loc)
            REFERENCES {{schema}}.localidad (cve_loc),
        CONSTRAINT fk_estacion_ageb FOREIGN KEY (cve_ageb)
            REFERENCES {{schema}}.ageb (cve_ageb),
        CONSTRAINT ck_estacion_lat CHECK (lat BETWEEN -90 AND 90),
        CONSTRAINT ck_estacion_lon CHECK (lon BETWEEN -180 AND 180),
        CONSTRAINT ck_estacion_geo CHECK (
            cve_ent IS NULL OR cvegeo IS NULL OR LEFT(cvegeo, 2) = cve_ent
        ),
        CONSTRAINT ck_estacion_loc CHECK (
            cvegeo IS NULL OR cve_loc IS NULL OR LEFT(cve_loc, 5) = cvegeo
        ),
        CONSTRAINT ck_estacion_ageb CHECK (
            cve_ageb IS NULL OR LEN(cve_ageb) = 9 OR cve_loc IS NULL OR LEFT(cve_ageb, 9) = cve_loc
        )
    );
END;
GO

IF OBJECT_ID('{{schema}}.sitio', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.sitio (
        sitio_id            INT IDENTITY CONSTRAINT pk_sitio PRIMARY KEY,
        codigo_sitio        NVARCHAR(50)  NOT NULL CONSTRAINT uq_sitio_codigo UNIQUE,
        nombre              NVARCHAR(200) NULL,
        lat                 DECIMAL(9, 6) NOT NULL,
        lon                 DECIMAL(9, 6) NOT NULL,
        geom                GEOGRAPHY     NOT NULL,
        altitud_m           DECIMAL(7, 1) NULL,
        cve_ent             CHAR(2)       NULL,
        cvegeo              CHAR(5)       NULL,
        cve_loc             CHAR(9)       NULL,
        cve_ageb            VARCHAR(13)   NULL,
        metodo_asignacion   VARCHAR(20)   NULL,
        en_limite           BIT           NOT NULL CONSTRAINT df_sitio_limite DEFAULT 0,
        sin_localidad       BIT           NOT NULL CONSTRAINT df_sitio_sinloc DEFAULT 0,
        fecha_alta          DATETIME2(0)  NOT NULL CONSTRAINT df_sitio_alta DEFAULT SYSUTCDATETIME(),
        fecha_actualizacion DATETIME2(0)  NULL,
        CONSTRAINT fk_sitio_entidad FOREIGN KEY (cve_ent)
            REFERENCES {{schema}}.entidad (cve_ent),
        CONSTRAINT fk_sitio_municipio FOREIGN KEY (cvegeo)
            REFERENCES {{schema}}.municipio (cvegeo),
        CONSTRAINT fk_sitio_localidad FOREIGN KEY (cve_loc)
            REFERENCES {{schema}}.localidad (cve_loc),
        CONSTRAINT fk_sitio_ageb FOREIGN KEY (cve_ageb)
            REFERENCES {{schema}}.ageb (cve_ageb),
        CONSTRAINT ck_sitio_lat CHECK (lat BETWEEN -90 AND 90),
        CONSTRAINT ck_sitio_lon CHECK (lon BETWEEN -180 AND 180),
        CONSTRAINT ck_sitio_metodo CHECK (
            metodo_asignacion IS NULL OR metodo_asignacion IN ('within', 'nearest', 'manual')
        ),
        CONSTRAINT ck_sitio_geo CHECK (
            cve_ent IS NULL OR cvegeo IS NULL OR LEFT(cvegeo, 2) = cve_ent
        ),
        CONSTRAINT ck_sitio_loc CHECK (
            cvegeo IS NULL OR cve_loc IS NULL OR LEFT(cve_loc, 5) = cvegeo
        ),
        CONSTRAINT ck_sitio_ageb CHECK (
            cve_ageb IS NULL OR LEN(cve_ageb) = 9 OR cve_loc IS NULL OR LEFT(cve_ageb, 9) = cve_loc
        )
    );
END;
GO

IF OBJECT_ID('{{schema}}.sitio_estacion', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.sitio_estacion (
        sitio_id     INT           NOT NULL,
        estacion_id  INT           NOT NULL,
        ranking      TINYINT       NOT NULL,
        distancia_km DECIMAL(6, 2) NOT NULL,
        d_altitud_m  DECIMAL(6, 1) NULL,
        peso_idw     DECIMAL(10, 6) NULL,
        metodo       VARCHAR(20)   NOT NULL CONSTRAINT df_sitio_estacion_metodo DEFAULT 'NEAREST',
        CONSTRAINT pk_sitio_estacion PRIMARY KEY (sitio_id, estacion_id),
        CONSTRAINT uq_sitio_estacion_ranking UNIQUE (sitio_id, ranking),
        CONSTRAINT fk_sitio_estacion_sitio FOREIGN KEY (sitio_id)
            REFERENCES {{schema}}.sitio (sitio_id),
        CONSTRAINT fk_sitio_estacion_estacion FOREIGN KEY (estacion_id)
            REFERENCES {{schema}}.estacion (estacion_id),
        CONSTRAINT ck_sitio_estacion_ranking CHECK (ranking BETWEEN 1 AND 20),
        CONSTRAINT ck_sitio_estacion_dist CHECK (distancia_km >= 0)
    );
END;
GO
