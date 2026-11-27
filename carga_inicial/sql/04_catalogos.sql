/* ============================================================
   Base homologada - catálogos iniciales
   ============================================================ */

SET NOCOUNT ON;
GO

/* ---------- Variables climáticas ---------- */
INSERT INTO {{schema}}.variable (variable_id, codigo, nombre, unidad, escala, agregacion, descripcion)
SELECT v.variable_id, v.codigo, v.nombre, v.unidad, v.escala, v.agregacion, v.descripcion
FROM (VALUES
    (1, 'PREC', 'Precipitación',            'mm', 'DIARIA', 'SUMA',  'Lluvia acumulada del día'),
    (2, 'TMAX', 'Temperatura máxima',       '°C', 'DIARIA', 'MEDIA', 'Promedio diario de la máxima'),
    (3, 'TMED', 'Temperatura media',        '°C', 'DIARIA', 'MEDIA', 'Promedio diario de la media'),
    (4, 'TMIN', 'Temperatura mínima',       '°C', 'DIARIA', 'MEDIA', 'Promedio diario de la mínima'),
    (5, 'EVAP', 'Evaporación',              'mm', 'DIARIA', 'SUMA',  'Evaporación acumulada del día')
) AS v(variable_id, codigo, nombre, unidad, escala, agregacion, descripcion)
WHERE NOT EXISTS (
    SELECT 1 FROM {{schema}}.variable t WHERE t.variable_id = v.variable_id
);
GO

/* ---------- Fuentes ---------- */
INSERT INTO {{schema}}.fuente (fuente_id, codigo, nombre, url_patron, frecuencia, licencia, notas)
SELECT f.fuente_id, f.codigo, f.nombre, f.url_patron, f.frecuencia, f.licencia, f.notas
FROM (VALUES
    (1, 'SMN_TXT_MENSUAL', 'SMN - Estadística mensual por estación',
        'https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/{edo}/mes{clave}.txt',
        'MENSUAL', 'Datos abiertos CONAGUA/SMN',
        'Emisión mensual. El modelo carga 2023+; sujeta a correcciones retroactivas.'),
    (2, 'SMN_TXT_DIARIO', 'SMN - Registro diario por estación',
        'https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Diarios/{edo}/dia{clave}.txt',
        'DIARIA', 'Datos abiertos CONAGUA/SMN',
        'Registro diario. El modelo carga 2023+; faltantes = NULO.'),
    (3, 'SIH_CSV_DIARIO', 'SIH - CSV diario por estación',
        'https://sih.conagua.gob.mx/basedatos/Climas/{clave_sih}.csv',
        'SEMANAL', 'Datos abiertos CONAGUA/SIH',
        'Encabezados heterogéneos; muchas estaciones sin datos recientes.'),
    (4, 'SMN_RED_CSV', 'SMN - Resumen mensual de red reducida',
        'https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/{AAAAMM}010000{tipo}.csv',
        'MENSUAL', 'Datos abiertos CONAGUA/SMN',
        'Solo 2013+. ~1,406 estaciones. El modelo carga 2023+. Base de los PDFs de temperatura.'),
    (5, 'PDF_ESTATAL', 'CONAGUA - PDF estatal mensual',
        'https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/{var}/{anio}.pdf',
        'MENSUAL', 'Datos abiertos CONAGUA/SMN',
        'Serie estatal 1985+; el modelo carga 2023+. Temperatura reproducible; lluvia no reproducible con datos públicos.'),
    (6, 'CALCULO_PROPIO', 'Cálculo propio a partir de datos diarios',
        NULL, 'DIARIA', 'Uso interno',
        'Agregación documentada en docs/agregaciones.md.'),
    (7, 'INEGI_MG', 'INEGI - Marco Geoestadístico',
        'https://www.inegi.org.mx/temas/mg/', 'ANUAL', 'INEGI',
        'Polígonos de entidad, municipio, localidad y AGEB.'),
    (8, 'INEGI_CENSO', 'INEGI - Censo de Población y Vivienda / Conteo',
        'https://www.inegi.org.mx/programas/ccpv/2020/', 'DECENAL', 'INEGI',
        'Población, edad, sexo, vivienda, educación. Niveles municipio, localidad y AGEB.'),
    (9, 'CONEVAL_IRS', 'CONEVAL - Índice de Rezago Social',
        'https://www.coneval.org.mx/Medicion/IRS/Paginas/Indice_Rezago_Social_2020.aspx',
        'IRREGULAR', 'CONEVAL',
        'Municipio, localidad y AGEB según edición.'),
    (10, 'CONAPO_IM', 'CONAPO - Índice de Marginación',
        'https://www.gob.mx/conapo/documentos/indices-de-marginacion-2020-284372',
        'IRREGULAR', 'CONAPO',
        'Municipio, localidad y AGEB según edición.'),
    (11, 'CONAPO_PROY', 'CONAPO - Proyecciones de población',
        'https://www.gob.mx/conapo/documentos/bases-de-datos-de-la-conciliacion-demografica-1950-a-2019-y-proyecciones-de-la-poblacion-de-mexico-2020-a-2070',
        'IRREGULAR', 'CONAPO',
        'Proyecciones municipales por edad y sexo.'),
    (12, 'DENUE', 'INEGI - Directorio Estadístico Nacional de Unidades Económicas',
        'https://www.inegi.org.mx/programas/denue/', 'SEMESTRAL', 'INEGI',
        'Unidades económicas con coordenadas; agregables a municipio/AGEB.')
) AS f(fuente_id, codigo, nombre, url_patron, frecuencia, licencia, notas)
WHERE NOT EXISTS (
    SELECT 1 FROM {{schema}}.fuente t WHERE t.fuente_id = f.fuente_id
);
GO

/* ---------- Indicadores de ejemplo ---------- */
INSERT INTO {{schema}}.indicador (indicador_id, dominio, codigo, nombre, unidad, niveles, descripcion)
SELECT i.indicador_id, i.dominio, i.codigo, i.nombre, i.unidad, i.niveles, i.descripcion
FROM (VALUES
    (1,  'DEMO',  'POB_TOTAL',          'Población total',                'personas', 'MUN,LOC,AGEB', 'Población residente'),
    (2,  'DEMO',  'POB_HOMBRES',        'Población hombres',              'personas', 'MUN,LOC,AGEB', NULL),
    (3,  'DEMO',  'POB_MUJERES',        'Población mujeres',              'personas', 'MUN,LOC,AGEB', NULL),
    (4,  'DEMO',  'EDAD_MEDIANA',       'Edad mediana',                   'años',     'MUN,LOC,AGEB', NULL),
    (5,  'DEMO',  'POB_0_14',           'Población de 0 a 14 años',       'personas', 'MUN,LOC,AGEB', NULL),
    (6,  'DEMO',  'POB_15_64',          'Población de 15 a 64 años',      'personas', 'MUN,LOC,AGEB', NULL),
    (7,  'DEMO',  'POB_65_MAS',         'Población de 65 años y más',     'personas', 'MUN,LOC,AGEB', NULL),
    (8,  'SOCIO', 'VIVIENDAS',          'Viviendas habitadas',            'viviendas', 'MUN,LOC,AGEB', NULL),
    (9,  'SOCIO', 'HOGARES',            'Hogares censales',               'hogares',  'MUN,LOC,AGEB', NULL),
    (10, 'SOCIO', 'ESCOLARIDAD_PROM',   'Grado promedio de escolaridad',  'años',     'MUN,LOC',     NULL),
    (11, 'ECON',  'PEA',                'Población económicamente activa','personas', 'MUN,LOC',     NULL),
    (12, 'SOCIO', 'INDICE_REZAGO_SOCIAL','Índice de Rezago Social',       'índice',   'MUN,LOC,AGEB', 'Metodología CONEVAL'),
    (13, 'SOCIO', 'INDICE_MARGINACION', 'Índice de Marginación',          'índice',   'MUN,LOC,AGEB', 'Metodología CONAPO'),
    (14, 'SOCIO', 'NSE_AMAI',           'Nivel socioeconómico AMAI',      'nivel',    'AGEB',        'Requiere licencia de AMAI'),
    (15, 'DEMO',  'POB_URBANA',         'Población urbana',               'personas', 'MUN,LOC',     NULL),
    (16, 'DEMO',  'POB_RURAL',          'Población rural',                'personas', 'MUN,LOC',     NULL)
) AS i(indicador_id, dominio, codigo, nombre, unidad, niveles, descripcion)
WHERE NOT EXISTS (
    SELECT 1 FROM {{schema}}.indicador t WHERE t.indicador_id = i.indicador_id
);
GO
