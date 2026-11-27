/* ============================================================
   Base homologada - índices
   Ejecutar después de 01a..01e
   ============================================================ */

SET NOCOUNT ON;
GO

/* --- Unicidad de claves externas (permiten NULL múltiple) --- */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ux_estacion_clave_smn' AND object_id = OBJECT_ID('{{schema}}.estacion'))
    CREATE UNIQUE INDEX ux_estacion_clave_smn
        ON {{schema}}.estacion (clave_smn)
        WHERE clave_smn IS NOT NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ux_estacion_clave_sih' AND object_id = OBJECT_ID('{{schema}}.estacion'))
    CREATE UNIQUE INDEX ux_estacion_clave_sih
        ON {{schema}}.estacion (clave_sih)
        WHERE clave_sih IS NOT NULL;
GO

/* --- Índices espaciales --- */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'sx_entidad_geom' AND object_id = OBJECT_ID('{{schema}}.entidad'))
    CREATE SPATIAL INDEX sx_entidad_geom ON {{schema}}.entidad (geom)
        USING GEOGRAPHY_AUTO_GRID WITH (CELLS_PER_OBJECT = 16);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'sx_municipio_geom' AND object_id = OBJECT_ID('{{schema}}.municipio'))
    CREATE SPATIAL INDEX sx_municipio_geom ON {{schema}}.municipio (geom)
        USING GEOGRAPHY_AUTO_GRID WITH (CELLS_PER_OBJECT = 16);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'sx_localidad_geom' AND object_id = OBJECT_ID('{{schema}}.localidad'))
    CREATE SPATIAL INDEX sx_localidad_geom ON {{schema}}.localidad (geom)
        USING GEOGRAPHY_AUTO_GRID WITH (CELLS_PER_OBJECT = 16);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'sx_ageb_geom' AND object_id = OBJECT_ID('{{schema}}.ageb'))
    CREATE SPATIAL INDEX sx_ageb_geom ON {{schema}}.ageb (geom)
        USING GEOGRAPHY_AUTO_GRID WITH (CELLS_PER_OBJECT = 16);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'sx_estacion_geom' AND object_id = OBJECT_ID('{{schema}}.estacion'))
    CREATE SPATIAL INDEX sx_estacion_geom ON {{schema}}.estacion (geom)
        USING GEOGRAPHY_AUTO_GRID WITH (CELLS_PER_OBJECT = 16);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'sx_sitio_geom' AND object_id = OBJECT_ID('{{schema}}.sitio'))
    CREATE SPATIAL INDEX sx_sitio_geom ON {{schema}}.sitio (geom)
        USING GEOGRAPHY_AUTO_GRID WITH (CELLS_PER_OBJECT = 16);
GO

/* --- Índices de consulta --- */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_clima_diario_var_fecha' AND object_id = OBJECT_ID('{{schema}}.clima_diario'))
    CREATE INDEX ix_clima_diario_var_fecha
        ON {{schema}}.clima_diario (variable_id, fecha)
        INCLUDE (estacion_id, valor, fuente_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_clima_mensual_var_periodo' AND object_id = OBJECT_ID('{{schema}}.clima_mensual'))
    CREATE INDEX ix_clima_mensual_var_periodo
        ON {{schema}}.clima_mensual (variable_id, anio, mes)
        INCLUDE (estacion_id, valor, origen, estado);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_sitio_cvegeo' AND object_id = OBJECT_ID('{{schema}}.sitio'))
    CREATE INDEX ix_sitio_cvegeo ON {{schema}}.sitio (cvegeo) INCLUDE (cve_loc);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_estacion_cvegeo' AND object_id = OBJECT_ID('{{schema}}.estacion'))
    CREATE INDEX ix_estacion_cvegeo ON {{schema}}.estacion (cvegeo) INCLUDE (cve_loc);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_dem_mun_anio' AND object_id = OBJECT_ID('{{schema}}.demografia_municipio'))
    CREATE INDEX ix_dem_mun_anio ON {{schema}}.demografia_municipio (anio, indicador_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_dem_loc_anio' AND object_id = OBJECT_ID('{{schema}}.demografia_localidad'))
    CREATE INDEX ix_dem_loc_anio ON {{schema}}.demografia_localidad (anio, indicador_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_dem_ageb_anio' AND object_id = OBJECT_ID('{{schema}}.demografia_ageb'))
    CREATE INDEX ix_dem_ageb_anio ON {{schema}}.demografia_ageb (anio, indicador_id);
GO
