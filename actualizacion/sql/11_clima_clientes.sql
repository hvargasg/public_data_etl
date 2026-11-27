-- Clima derivado para las ubicaciones de clientes (dbo.Clientes).
--
-- El cruce no se guarda por cliente individual ni por día: se usan celdas de
-- ~1 km (lat/lon redondeadas a 2 decimales), un puente con las k estaciones
-- OPERANDO más cercanas y un hecho mensual derivado. El detalle de las
-- decisiones está en docs/clima_clientes.md.
--
-- Es idempotente: el ETL crea las estructuras la primera vez y después no
-- hace nada.

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

/* Celda de ~1 km que agrupa una o más ubicaciones de clientes. */
IF OBJECT_ID('{{schema}}.cliente_ubicacion', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.cliente_ubicacion (
        ubicacion_id INT IDENTITY CONSTRAINT pk_cliente_ubicacion PRIMARY KEY,
        lat          DECIMAL(9, 6) NOT NULL,
        lon          DECIMAL(9, 6) NOT NULL,
        geom         GEOGRAPHY     NOT NULL,
        altitud_m    DECIMAL(7, 1) NULL,
        cve_ent      CHAR(2)       NULL,
        cvegeo       CHAR(5)       NULL,
        fecha_carga  DATETIME2(0)  NOT NULL
            CONSTRAINT df_cliente_ubicacion_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT uq_cliente_ubicacion_celda UNIQUE (lat, lon),
        CONSTRAINT fk_cliente_ubicacion_entidad FOREIGN KEY (cve_ent)
            REFERENCES {{schema}}.entidad (cve_ent),
        CONSTRAINT fk_cliente_ubicacion_municipio FOREIGN KEY (cvegeo)
            REFERENCES {{schema}}.municipio (cvegeo),
        CONSTRAINT ck_cliente_ubicacion_lat CHECK (lat BETWEEN -90 AND 90),
        CONSTRAINT ck_cliente_ubicacion_lon CHECK (lon BETWEEN -180 AND 180),
        CONSTRAINT ck_cliente_ubicacion_geo CHECK (
            cve_ent IS NULL OR cvegeo IS NULL OR LEFT(cvegeo, 2) = cve_ent
        )
    );
END;
GO

/* Enlace cliente-domicilio -> celda. Cliente_id y Direccion_id replican los
   tipos de dbo.Clientes; la integridad con dbo la mantiene el ETL. */
IF OBJECT_ID('{{schema}}.cliente_ubicacion_map', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.cliente_ubicacion_map (
        Cliente_id   VARCHAR(255) NOT NULL,
        Direccion_id SMALLINT     NOT NULL,
        ubicacion_id INT          NOT NULL,
        fecha_carga  DATETIME2(0) NOT NULL
            CONSTRAINT df_cliente_ubicacion_map_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_cliente_ubicacion_map PRIMARY KEY (Cliente_id, Direccion_id),
        CONSTRAINT fk_cliente_ubicacion_map_ubicacion FOREIGN KEY (ubicacion_id)
            REFERENCES {{schema}}.cliente_ubicacion (ubicacion_id)
    );
END;
GO

/* Puente: las k estaciones OPERANDO más cercanas a cada celda. */
IF OBJECT_ID('{{schema}}.cliente_estacion', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.cliente_estacion (
        ubicacion_id INT            NOT NULL,
        estacion_id  INT            NOT NULL,
        ranking      TINYINT        NOT NULL,
        distancia_km DECIMAL(6, 2)  NOT NULL,
        d_altitud_m  DECIMAL(6, 1)  NULL,
        peso_idw     DECIMAL(10, 6) NULL,
        fecha_carga  DATETIME2(0)   NOT NULL
            CONSTRAINT df_cliente_estacion_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_cliente_estacion PRIMARY KEY (ubicacion_id, estacion_id),
        CONSTRAINT uq_cliente_estacion_ranking UNIQUE (ubicacion_id, ranking),
        CONSTRAINT fk_cliente_estacion_ubicacion FOREIGN KEY (ubicacion_id)
            REFERENCES {{schema}}.cliente_ubicacion (ubicacion_id),
        CONSTRAINT fk_cliente_estacion_estacion FOREIGN KEY (estacion_id)
            REFERENCES {{schema}}.estacion (estacion_id),
        CONSTRAINT ck_cliente_estacion_ranking CHECK (ranking BETWEEN 1 AND 20),
        CONSTRAINT ck_cliente_estacion_dist CHECK (distancia_km >= 0)
    );
END;
GO

/* Hecho derivado mensual: una fila por celda, variable, mes y método. */
IF OBJECT_ID('{{schema}}.clima_cliente_mensual', 'U') IS NULL
BEGIN
    CREATE TABLE {{schema}}.clima_cliente_mensual (
        ubicacion_id  INT            NOT NULL,
        variable_id   TINYINT        NOT NULL,
        anio          SMALLINT       NOT NULL,
        mes           TINYINT        NOT NULL,
        valor         DECIMAL(10, 3) NULL,
        metodo        VARCHAR(20)    NOT NULL,
        n_estaciones  TINYINT        NULL,
        fecha_calculo DATETIME2(0)   NOT NULL
            CONSTRAINT df_clima_cliente_carga DEFAULT SYSUTCDATETIME(),
        CONSTRAINT pk_clima_cliente_mensual
            PRIMARY KEY (ubicacion_id, variable_id, anio, mes, metodo),
        CONSTRAINT fk_clima_cliente_ubicacion FOREIGN KEY (ubicacion_id)
            REFERENCES {{schema}}.cliente_ubicacion (ubicacion_id),
        CONSTRAINT fk_clima_cliente_variable FOREIGN KEY (variable_id)
            REFERENCES {{schema}}.variable (variable_id),
        CONSTRAINT ck_clima_cliente_metodo CHECK (metodo IN ('NEAREST', 'IDW')),
        CONSTRAINT ck_clima_cliente_mes CHECK (mes BETWEEN 1 AND 12),
        CONSTRAINT ck_clima_cliente_anio CHECK (anio BETWEEN 2023 AND 2100)
    );
END;
GO

/* Índices de consulta. */
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'ix_cliente_ubicacion_map_ubicacion'
                 AND object_id = OBJECT_ID('{{schema}}.cliente_ubicacion_map'))
    CREATE INDEX ix_cliente_ubicacion_map_ubicacion
        ON {{schema}}.cliente_ubicacion_map (ubicacion_id)
        INCLUDE (Cliente_id, Direccion_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'ix_cliente_estacion_estacion'
                 AND object_id = OBJECT_ID('{{schema}}.cliente_estacion'))
    CREATE INDEX ix_cliente_estacion_estacion
        ON {{schema}}.cliente_estacion (estacion_id)
        INCLUDE (ubicacion_id, ranking, peso_idw);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'ix_clima_cliente_var_periodo'
                 AND object_id = OBJECT_ID('{{schema}}.clima_cliente_mensual'))
    CREATE INDEX ix_clima_cliente_var_periodo
        ON {{schema}}.clima_cliente_mensual (variable_id, anio, mes)
        INCLUDE (ubicacion_id, valor, metodo, n_estaciones);
GO

/* Vista: celda con nombres geográficos y número de domicilios que agrupa. */
CREATE OR ALTER VIEW {{schema}}.vw_cliente_ubicacion
AS
SELECT u.ubicacion_id, u.lat, u.lon, u.altitud_m,
       u.cve_ent, en.nom_ent, u.cvegeo, mu.nom_mun,
       (SELECT COUNT(*) FROM {{schema}}.cliente_ubicacion_map m
        WHERE m.ubicacion_id = u.ubicacion_id) AS domicilios
FROM {{schema}}.cliente_ubicacion u
LEFT JOIN {{schema}}.entidad en   ON en.cve_ent = u.cve_ent
LEFT JOIN {{schema}}.municipio mu ON mu.cvegeo = u.cvegeo;
GO

/* Vista: puente con datos de la estación, legible por cliente. */
CREATE OR ALTER VIEW {{schema}}.vw_cliente_estacion
AS
SELECT m.Cliente_id, m.Direccion_id, m.ubicacion_id,
       ce.ranking, ce.distancia_km, ce.d_altitud_m, ce.peso_idw,
       e.estacion_id, e.clave_smn, e.nombre AS estacion_nombre,
       e.situacion, e.altitud_m AS estacion_altitud_m
FROM {{schema}}.cliente_estacion ce
JOIN {{schema}}.cliente_ubicacion_map m ON m.ubicacion_id = ce.ubicacion_id
JOIN {{schema}}.estacion e             ON e.estacion_id = ce.estacion_id;
GO

/* Vista: clima mensual derivado, consultable por Cliente_id y Direccion_id. */
CREATE OR ALTER VIEW {{schema}}.vw_clima_cliente_mensual
AS
SELECT m.Cliente_id, m.Direccion_id, c.ubicacion_id,
       u.cve_ent, en.nom_ent, u.cvegeo, mu.nom_mun,
       c.variable_id, var.codigo AS variable, var.unidad,
       c.anio, c.mes, c.valor, c.metodo, c.n_estaciones, c.fecha_calculo
FROM {{schema}}.clima_cliente_mensual c
JOIN {{schema}}.cliente_ubicacion_map m ON m.ubicacion_id = c.ubicacion_id
JOIN {{schema}}.cliente_ubicacion u     ON u.ubicacion_id = c.ubicacion_id
JOIN {{schema}}.variable var            ON var.variable_id = c.variable_id
LEFT JOIN {{schema}}.entidad en         ON en.cve_ent = u.cve_ent
LEFT JOIN {{schema}}.municipio mu       ON mu.cvegeo = u.cvegeo;
GO

/* Vista auxiliar: clima diario vigente por estación (prioridad de fuentes). */
CREATE OR ALTER VIEW {{schema}}.vw_clima_diario_vigente
AS
WITH ranked AS (
    SELECT d.estacion_id, d.variable_id, d.fecha, d.valor, d.fuente_id,
           d.flag_calidad,
           ROW_NUMBER() OVER (
               PARTITION BY d.estacion_id, d.variable_id, d.fecha
               ORDER BY CASE f.codigo
                            WHEN 'SIH_CSV_DIARIO' THEN 0
                            WHEN 'SMN_TXT_DIARIO' THEN 1
                            ELSE 9
                        END
           ) AS rn
    FROM {{schema}}.clima_diario d
    JOIN {{schema}}.fuente f ON f.fuente_id = d.fuente_id
    WHERE d.valor IS NOT NULL
)
SELECT estacion_id, variable_id, fecha, valor, fuente_id, flag_calidad
FROM ranked
WHERE rn = 1;
GO

/* Vista diaria por estación: aportación de cada vecina a cada domicilio.
   Es la base del cálculo IDW y sirve para auditar. */
CREATE OR ALTER VIEW {{schema}}.vw_clima_cliente_diario_estacion
AS
SELECT m.Cliente_id, m.Direccion_id, ce.ubicacion_id,
       ce.estacion_id, ce.ranking, ce.distancia_km, ce.peso_idw,
       d.variable_id, var.codigo AS variable, var.unidad,
       d.fecha, d.valor, d.fuente_id, d.flag_calidad
FROM {{schema}}.cliente_estacion ce
JOIN {{schema}}.cliente_ubicacion_map m ON m.ubicacion_id = ce.ubicacion_id
JOIN {{schema}}.vw_clima_diario_vigente d ON d.estacion_id = ce.estacion_id
JOIN {{schema}}.variable var            ON var.variable_id = d.variable_id;
GO

/* Vista diaria derivada por domicilio con IDW. Los pesos se renormalizan
   sobre las estaciones que sí tienen valor ese día. */
CREATE OR ALTER VIEW {{schema}}.vw_clima_cliente_diario
AS
SELECT v.Cliente_id, v.Direccion_id, v.ubicacion_id,
       v.variable_id, v.variable, v.unidad, v.fecha,
       SUM(v.valor * v.peso_idw) / NULLIF(SUM(v.peso_idw), 0) AS valor,
       COUNT(DISTINCT v.estacion_id) AS n_estaciones,
       CAST(AVG(v.distancia_km) AS DECIMAL(6, 2)) AS distancia_media_km
FROM {{schema}}.vw_clima_cliente_diario_estacion v
WHERE v.peso_idw IS NOT NULL
GROUP BY v.Cliente_id, v.Direccion_id, v.ubicacion_id,
         v.variable_id, v.variable, v.unidad, v.fecha;
GO

/* Variante NEAREST diaria: solo la estación más cercana (ranking = 1). */
CREATE OR ALTER VIEW {{schema}}.vw_clima_cliente_diario_cercano
AS
SELECT Cliente_id, Direccion_id, ubicacion_id,
       variable_id, variable, unidad, fecha,
       valor, CAST(1 AS TINYINT) AS n_estaciones,
       distancia_km AS distancia_media_km
FROM {{schema}}.vw_clima_cliente_diario_estacion
WHERE ranking = 1;
GO
