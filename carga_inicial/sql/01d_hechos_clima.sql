/* ============================================================
   Base homologada - hechos de clima
   diario / mensual (calculado y oficial) / estatal / sitio
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

/* Observaciones diarias por estación. Una fila por fuente. */
IF OBJECT_ID('{{schema}}.clima_diario', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.clima_diario (
        estacion_id  INT           NOT NULL,
        variable_id  TINYINT       NOT NULL,
        fecha        DATE          NOT NULL,
        valor        DECIMAL(10, 3) NULL,
        fuente_id    TINYINT       NOT NULL,
        flag_calidad VARCHAR(12)   NULL,
        fecha_carga  DATETIME2(0)  NOT NULL CONSTRAINT df_clima_diario_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_clima_diario PRIMARY KEY (estacion_id, variable_id, fecha, fuente_id),
        CONSTRAINT fk_clima_diario_estacion FOREIGN KEY (estacion_id)
            REFERENCES {{schema}}.estacion (estacion_id),
        CONSTRAINT fk_clima_diario_variable FOREIGN KEY (variable_id)
            REFERENCES {{schema}}.variable (variable_id),
        CONSTRAINT fk_clima_diario_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id),
        CONSTRAINT ck_clima_diario_flag CHECK (
            flag_calidad IS NULL OR flag_calidad IN ('OK', 'NULO', 'OUTLIER', 'SOSPECHOSO', 'ESTIMADO')
        ),
        CONSTRAINT ck_clima_diario_fecha CHECK (fecha >= '2023-01-01')
    );
END;
GO

/* Mensual por estación: coexisten CALCULADO (propio) y OFICIAL (SMN/SIH).
   La vista vw_clima_mensual_vigente da prioridad al oficial. */
IF OBJECT_ID('{{schema}}.clima_mensual', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.clima_mensual (
        estacion_id    INT           NOT NULL,
        variable_id    TINYINT       NOT NULL,
        anio           SMALLINT      NOT NULL,
        mes            TINYINT       NOT NULL,
        valor          DECIMAL(10, 3) NULL,
        origen         VARCHAR(12)   NOT NULL,
        estado         VARCHAR(12)   NOT NULL,
        fuente_id      TINYINT       NOT NULL,
        dias_con_dato  TINYINT       NULL,
        dias_esperados TINYINT       NULL,
        completo       BIT           NULL,
        fecha_corte    DATE          NULL,
        fecha_carga    DATETIME2(0)  NOT NULL CONSTRAINT df_clima_mensual_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_clima_mensual PRIMARY KEY (estacion_id, variable_id, anio, mes, origen, fuente_id),
        CONSTRAINT fk_clima_mensual_estacion FOREIGN KEY (estacion_id)
            REFERENCES {{schema}}.estacion (estacion_id),
        CONSTRAINT fk_clima_mensual_variable FOREIGN KEY (variable_id)
            REFERENCES {{schema}}.variable (variable_id),
        CONSTRAINT fk_clima_mensual_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id),
        CONSTRAINT ck_clima_mensual_mes CHECK (mes BETWEEN 1 AND 12),
        CONSTRAINT ck_clima_mensual_anio CHECK (anio BETWEEN 2023 AND 2100),
        CONSTRAINT ck_clima_mensual_origen CHECK (origen IN ('CALCULADO', 'OFICIAL')),
        CONSTRAINT ck_clima_mensual_estado CHECK (estado IN ('PRELIMINAR', 'DEFINITIVO'))
    );
END;
GO

/* Serie estatal mensual (PDFs de CONAGUA). El modelo carga 2023+. */
IF OBJECT_ID('{{schema}}.clima_estatal_mensual', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.clima_estatal_mensual (
        cve_ent     CHAR(2)       NOT NULL,
        variable_id TINYINT       NOT NULL,
        anio        SMALLINT      NOT NULL,
        mes         TINYINT       NOT NULL,
        valor       DECIMAL(10, 3) NULL,
        fuente_id   TINYINT       NOT NULL,
        fecha_carga DATETIME2(0)  NOT NULL CONSTRAINT df_clima_estatal_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_clima_estatal PRIMARY KEY (cve_ent, variable_id, anio, mes, fuente_id),
        CONSTRAINT fk_clima_estatal_entidad FOREIGN KEY (cve_ent)
            REFERENCES {{schema}}.entidad (cve_ent),
        CONSTRAINT fk_clima_estatal_variable FOREIGN KEY (variable_id)
            REFERENCES {{schema}}.variable (variable_id),
        CONSTRAINT fk_clima_estatal_fuente FOREIGN KEY (fuente_id)
            REFERENCES {{schema}}.fuente (fuente_id),
        CONSTRAINT ck_clima_estatal_mes CHECK (mes BETWEEN 1 AND 12),
        CONSTRAINT ck_clima_estatal_anio CHECK (anio BETWEEN 2023 AND 2100)
    );
END;
GO

/* Clima derivado en los sitios (NEAREST o IDW). Separado del observado. */
IF OBJECT_ID('{{schema}}.clima_sitio_mensual', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.clima_sitio_mensual (
        sitio_id      INT           NOT NULL,
        variable_id   TINYINT       NOT NULL,
        anio          SMALLINT      NOT NULL,
        mes           TINYINT       NOT NULL,
        valor         DECIMAL(10, 3) NULL,
        metodo        VARCHAR(20)   NOT NULL,
        n_estaciones  TINYINT       NULL,
        fecha_calculo DATETIME2(0)  NOT NULL CONSTRAINT df_clima_sitio_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_clima_sitio_mensual PRIMARY KEY (sitio_id, variable_id, anio, mes, metodo),
        CONSTRAINT fk_clima_sitio_sitio FOREIGN KEY (sitio_id)
            REFERENCES {{schema}}.sitio (sitio_id),
        CONSTRAINT fk_clima_sitio_variable FOREIGN KEY (variable_id)
            REFERENCES {{schema}}.variable (variable_id),
        CONSTRAINT ck_clima_sitio_metodo CHECK (metodo IN ('NEAREST', 'IDW')),
        CONSTRAINT ck_clima_sitio_mes CHECK (mes BETWEEN 1 AND 12),
        CONSTRAINT ck_clima_sitio_anio CHECK (anio BETWEEN 2023 AND 2100)
    );
END;
GO
