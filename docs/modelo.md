# Modelo de datos

El modelo vive en la base **`DataLake`**, schema **`datos_publicos`**, **sin prefijo**. Usa
nombres limpios (`variable`, `municipio`, `clima_diario`, etc.) y convive con
las tablas existentes, en particular `dbo.clima_hist`. Es un **modelo en
estrella** con dimensiones geográficas y de catálogo, y hechos de clima y
demografía.

---

## 1. Principios

1. **Claves oficiales del INEGI** en toda la jerarquía geográfica.
2. **Separación de granos**: diario, mensual, estatal y sitio no se mezclan en
   una sola tabla.
3. **Coexistencia de calculado y oficial**: el mismo periodo puede tener una
   fila propia y una oficial.
4. **Trazabilidad**: cada hecho guarda `fuente_id` y `fecha_carga`; el mensual
   guarda además `fecha_corte`, `dias_con_dato` y `completo`.
5. **Idempotencia**: las cargas borran e insertan por rango y fuente, no
   duplican.
6. **Sin credenciales en el código**: la conexión se configura por entorno.
7. **Ventana 2023+**: el modelo solo almacena clima desde 2023-01-01. Los
   `CHECK` de las tablas de clima y los valores por defecto del ETL lo imponen.

Todo el modelo vive en la base **`DataLake`**, schema **`datos_publicos`**.

---

## 1.1 Modelo estrella: dimensiones, hechos y puente

El diseño separa **atributos descriptivos** (dimensiones) de **mediciones**
(hechos). Las tablas de hechos solo contienen claves, medidas y metadatos de
calidad; los nombres, geometrías, unidades y descripciones viven una sola vez
en las dimensiones.

### Dimensiones

| Tabla | Grano | Atributos |
|---|---|---|
| `variable` | variable climática | código, nombre, unidad, escala, agregación |
| `fuente` | fuente | código, nombre, URL, frecuencia, licencia |
| `indicador` | indicador demográfico/social/económico | código, dominio, nombre, unidad, niveles |
| `entidad` | entidad | nombre, geometría, versión MG |
| `municipio` | municipio | nombre, geometría, FK entidad |
| `localidad` | localidad | nombre, ámbito, geometría, FK municipio |
| `ageb` | AGEB | tipo, geometría, FK municipio/localidad |
| `estacion` | estación | claves SMN/SIH, coordenadas, altitud, FK geografía |
| `sitio` | sitio propio | código, coordenadas, altitud, FK geografía |
| `cliente_ubicacion` | celda de ~1 km | coordenadas, geometría, FK geografía |

La geografía es una **dimensión copo de nieve** (`entidad → municipio →
localidad → AGEB`): así no se repiten nombres ni polígonos en estaciones,
sitios o hechos. Las claves son las oficiales del INEGI.

### Puente

| Tabla | Función |
|---|---|
| `sitio_estacion` | relación N:M sitio-estación, con ranking, distancia, diferencia de altitud y peso IDW |
| `cliente_ubicacion_map` | enlace domicilio de cliente → celda de ~1 km |
| `cliente_estacion` | relación N:M celda-estación, con ranking, distancia, diferencia de altitud y peso IDW |

### Hechos

| Tabla | Grano | Medidas |
|---|---|---|
| `clima_diario` | estación-variable-fecha-fuente | valor, flag de calidad |
| `clima_mensual` | estación-variable-año-mes-origen-fuente | valor, días con dato, días esperados, completo, fecha de corte |
| `clima_estatal_mensual` | entidad-variable-año-mes-fuente | valor |
| `clima_sitio_mensual` | sitio-variable-año-mes-método | valor, número de estaciones |
| `clima_cliente_mensual` | celda-variable-año-mes-método | valor, número de estaciones |
| `demografia_municipio` | municipio-año-indicador-fuente | valor |
| `demografia_localidad` | localidad-año-indicador-fuente | valor |
| `demografia_ageb` | AGEB-año-indicador-fuente | valor |

### Tabla de operación

`carga_log` no es una tabla estrella: registra ejecuciones, filas y errores
del ETL.

### Por qué no hay datos redundantes

- Los **nombres, geometrías, unidades y descripciones** existen solo en las
  dimensiones; los hechos guardan la clave, no el texto.
- La **geografía** está normalizada por niveles. Una estación o un sitio
  referencian `cve_ent`, `cvegeo`, `cve_loc` y `cve_ageb`; no duplican nombres
  ni polígonos. Esas claves son llaves foráneas a la dimensión geográfica, no
  atributos descriptivos repetidos; los `CHECK` garantizan la coherencia
  jerárquica (`cvegeo` empieza con `cve_ent`, `cve_loc` con `cvegeo`, etc.).
- Las tres tablas de **demografía** no son redundantes: cada una tiene un grano
  distinto (municipio, localidad, AGEB) y las tres mantienen integridad
  referencial.
- `clima_estatal_mensual` y `clima_mensual` **no son redundantes**:
  representan niveles y fuentes distintos (entidad-mes vs. estación-mes).
- `clima_sitio_mensual` es un **hecho derivado persistido** por rendimiento;
  se puede reconstruir desde `sitio_estacion` y la serie mensual de
  estaciones. Si se prefiere cero duplicación lógica, se puede reemplazar por
  una vista.
- `clima_cliente_mensual` sigue la misma regla: es un hecho derivado persistido
  por rendimiento, reconstruible desde `cliente_estacion` y
  `vw_clima_mensual_vigente`. El clima **diario** por cliente no se persiste:
  se expone con las vistas `vw_clima_cliente_diario` y
  `vw_clima_cliente_diario_cercano`. El detalle está en
  [`clima_clientes.md`](clima_clientes.md).
- El **tiempo** se modela como dimensión degenerada (`fecha`, `anio`, `mes`).
  No se crea una tabla `tiempo` porque no hay atributos de calendario
  adicionales; si más adelante necesitas trimestres, semanas o feriados, se
  puede agregar y migrar las claves.


---

## 2. Vista general

```
entidad (cve_ent)
   │
   ├── municipio (cvegeo)
   │      │
   │      ├── localidad (cve_loc)
   │      │      │
   │      │      └── ageb (cve_ageb, opcional)
   │      │
   │      └── demografia_municipio
   │             demografia_localidad
   │             demografia_ageb
   │
   ├── clima_estatal_mensual
   │
   └── estacion (cve_ent, cvegeo, cve_loc, cve_ageb)
          │
          ├── clima_diario
          ├── clima_mensual
          ├── sitio_estacion ── sitio
          │                         │
          │                         └── clima_sitio_mensual
          └── cliente_estacion ── cliente_ubicacion
                                    │
                                    ├── cliente_ubicacion_map
                                    └── clima_cliente_mensual
```

---

## 3. Catálogos

### `variable`

Define las variables climáticas y **cómo se agregan** de diario a mensual.

| Columna | Tipo | Notas |
|---|---|---|
| `variable_id` | `TINYINT` PK | 1..5 |
| `codigo` | `VARCHAR(20)` unique | `PREC`, `TMAX`, `TMED`, `TMIN`, `EVAP` |
| `nombre` | `NVARCHAR(100)` | nombre legible |
| `unidad` | `NVARCHAR(10)` | `mm`, `°C` |
| `escala` | `VARCHAR(10)` | `DIARIA` / `MENSUAL` |
| `agregacion` | `VARCHAR(10)` | `SUMA` / `MEDIA` |
| `descripcion` | `NVARCHAR(300)` | |

La columna `agregacion` es la que usa `actualizacion/build_mensual.py`; no está codificada en
el ETL.

### `fuente`

Catálogo de fuentes.

| Columna | Tipo | Notas |
|---|---|---|
| `fuente_id` | `TINYINT` PK | |
| `codigo` | `VARCHAR(40)` unique | ver [fuentes.md](fuentes.md) |
| `nombre` | `NVARCHAR(200)` | |
| `url_patron` | `NVARCHAR(500)` | plantilla de descarga |
| `frecuencia` | `VARCHAR(30)` | |
| `fecha_emision` | `DATE` | |
| `licencia` | `NVARCHAR(200)` | |
| `notas` | `NVARCHAR(1000)` | |

Los `url_patron` sembrados apuntan a los portales oficiales. La lista completa
con fichas de producto, ZIP/XLSX directos y ejemplos verificados está en
[enlaces.md](enlaces.md).

### `indicador`

Catálogo de indicadores demográficos, sociales y económicos.

| Columna | Tipo | Notas |
|---|---|---|
| `indicador_id` | `SMALLINT` PK | |
| `dominio` | `VARCHAR(20)` | `DEMO`, `SOCIO`, `ECON` |
| `codigo` | `VARCHAR(40)` unique | se usa en los archivos de carga |
| `nombre` | `NVARCHAR(200)` | |
| `unidad` | `NVARCHAR(20)` | |
| `niveles` | `NVARCHAR(50)` | `MUN`, `LOC`, `AGEB` |
| `descripcion` | `NVARCHAR(500)` | |

Para agregar un indicador nuevo, inserta una fila aquí **antes** de cargar el
archivo; `carga_inicial/load_demografia.py` resuelve por `codigo`.

### `carga_log`

Bitácora de ejecuciones.

| Columna | Tipo | Notas |
|---|---|---|
| `carga_id` | `BIGINT` identity PK | |
| `proceso` | `VARCHAR(50)` | nombre del paso |
| `fuente_id` | `TINYINT` FK | nullable |
| `inicio` / `fin` | `DATETIME2(0)` | UTC |
| `filas` | `INT` | filas procesadas |
| `estado` | `VARCHAR(20)` | `EN_PROCESO`, `OK`, `ERROR` |
| `mensaje` | `NVARCHAR(1000)` | error si aplica |

---

## 4. Geografía

### `entidad`

| Columna | Tipo | Notas |
|---|---|---|
| `cve_ent` | `CHAR(2)` PK | |
| `nom_ent` | `NVARCHAR(100)` | |
| `version_mg` | `CHAR(4)` | versión del Marco Geoestadístico |
| `geom` | `GEOGRAPHY` | polígono |

### `municipio`

| Columna | Tipo | Notas |
|---|---|---|
| `cvegeo` | `CHAR(5)` PK | `cve_ent + cve_mun` |
| `cve_ent` | `CHAR(2)` FK | |
| `cve_mun` | `CHAR(3)` | |
| `nom_mun` | `NVARCHAR(150)` | |
| `version_mg` | `CHAR(4)` | |
| `geom` | `GEOGRAPHY` | |

### `localidad`

| Columna | Tipo | Notas |
|---|---|---|
| `cve_loc` | `CHAR(9)` PK | `cvegeo + cve_loc(4)` |
| `cvegeo` | `CHAR(5)` FK | |
| `cve_loc_inegi` | `CHAR(4)` | clave de localidad del INEGI |
| `nom_loc` | `NVARCHAR(200)` | |
| `ambito` | `VARCHAR(10)` | `URBANA` / `RURAL` |
| `version_mg` | `CHAR(4)` | |
| `geom` | `GEOGRAPHY` | polígono |

### `ageb` (opcional)

| Columna | Tipo | Notas |
|---|---|---|
| `cve_ageb` | `VARCHAR(13)` PK | 13 urbana, 9 rural |
| `cve_loc` | `CHAR(9)` FK nullable | solo AGEB urbana |
| `cvegeo` | `CHAR(5)` FK | municipio |
| `cve_ageb_inegi` | `VARCHAR(4)` | puede ser alfanumérico (`216A`) |
| `tipo` | `VARCHAR(10)` | `URBANA` / `RURAL` |
| `version_mg` | `CHAR(4)` | |
| `geom` | `GEOGRAPHY` | |

Restricciones:

- `LEN(cve_ageb) IN (9, 13)`.
- `LEFT(cve_ageb, 5) = cvegeo`.
- Si es urbana (13), `LEFT(cve_ageb, 9) = cve_loc`.

La AGEB es **opcional**: puedes cargar entidad/municipio/localidad sin AGEB y
el resto del modelo funciona. Ver [ageb.md](ageb.md).

---

## 5. Estaciones y sitios

### `estacion`

Una fila por estación del SMN (y, si se enlaza, su clave SIH).

| Columna | Tipo | Notas |
|---|---|---|
| `estacion_id` | `INT` identity PK | |
| `clave_smn` | `VARCHAR(10)` | unique filtrado |
| `clave_sih` | `VARCHAR(20)` | unique filtrado |
| `nombre` | `NVARCHAR(200)` | |
| `lat`, `lon` | `DECIMAL(9,6)` | WGS84 |
| `geom` | `GEOGRAPHY` | punto |
| `altitud_m` | `DECIMAL(7,1)` | |
| `cve_ent`, `cvegeo`, `cve_loc`, `cve_ageb` | | geografía asignada |
| `situacion` | `VARCHAR(20)` | `OPERANDO`, etc. |
| `tipo` | `NVARCHAR(50)` | |
| `organismo`, `cuenca` | | |
| `inicio`, `mas_reciente` | `DATE` | cobertura declarada |
| `url_mensual`, `url_diario`, `url_extremos` | | descarga directa |
| `version_indice` | `VARCHAR(20)` | versión del GeoJSON |
| `fecha_carga` | `DATETIME2(0)` | |

### `sitio`

Puntos propios (plantas, sucursales, parcelas, etc.).

| Columna | Tipo | Notas |
|---|---|---|
| `sitio_id` | `INT` identity PK | |
| `codigo_sitio` | `NVARCHAR(50)` unique | clave de negocio |
| `nombre` | `NVARCHAR(200)` | |
| `lat`, `lon` | `DECIMAL(9,6)` | |
| `geom` | `GEOGRAPHY` | |
| `altitud_m` | `DECIMAL(7,1)` | |
| `cve_ent`, `cvegeo`, `cve_loc`, `cve_ageb` | | asignación espacial |
| `metodo_asignacion` | `VARCHAR(20)` | `within`, `nearest`, `manual` |
| `en_limite` | `BIT` | el punto cae en más de un municipio |
| `sin_localidad` | `BIT` | no se encontró localidad |
| `fecha_alta`, `fecha_actualizacion` | `DATETIME2(0)` | |

### `sitio_estacion`

Puente con las `k` estaciones más cercanas.

| Columna | Tipo | Notas |
|---|---|---|
| `sitio_id`, `estacion_id` | PK compuesta | |
| `ranking` | `TINYINT` | 1 = más cercana |
| `distancia_km` | `DECIMAL(6,2)` | |
| `d_altitud_m` | `DECIMAL(6,1)` | estación - sitio |
| `peso_idw` | `DECIMAL(10,6)` | normalizado a suma 1 |
| `metodo` | `VARCHAR(20)` | `NEAREST`, `IDW` |

---

## 6. Hechos de clima

### `clima_diario`

| Columna | Tipo | Notas |
|---|---|---|
| `estacion_id` | `INT` FK | |
| `variable_id` | `TINYINT` FK | |
| `fecha` | `DATE` | |
| `valor` | `DECIMAL(10,3)` | nullable |
| `fuente_id` | `TINYINT` FK | |
| `flag_calidad` | `VARCHAR(12)` | `OK`, `NULO`, `OUTLIER`, `SOSPECHOSO`, `ESTIMADO` |
| `fecha_carga` | `DATETIME2(0)` | |

PK: `(estacion_id, variable_id, fecha, fuente_id)`. Permite que la misma
estación/variable/día exista en SMN y en SIH sin colisionar.

CHECK: `fecha >= '2023-01-01'` (ventana vigente del modelo).

### `clima_mensual`

| Columna | Tipo | Notas |
|---|---|---|
| `estacion_id` | `INT` FK | |
| `variable_id` | `TINYINT` FK | |
| `anio` | `SMALLINT` | |
| `mes` | `TINYINT` | 1..12 |
| `valor` | `DECIMAL(10,3)` | |
| `origen` | `VARCHAR(12)` | `CALCULADO` / `OFICIAL` |
| `estado` | `VARCHAR(12)` | `PRELIMINAR` / `DEFINITIVO` |
| `fuente_id` | `TINYINT` FK | |
| `dias_con_dato` | `TINYINT` | |
| `dias_esperados` | `TINYINT` | |
| `completo` | `BIT` | |
| `fecha_corte` | `DATE` | último día con dato o emisión oficial |
| `fecha_carga` | `DATETIME2(0)` | |

PK: `(estacion_id, variable_id, anio, mes, origen, fuente_id)`.

CHECK: `anio BETWEEN 2023 AND 2100`.

Esta PK es la pieza clave: permite **dos filas para el mismo periodo** (una
calculada y una oficial) sin sobrescribirse.

### `clima_estatal_mensual`

Serie estatal de PDFs/migración.

| Columna | Tipo |
|---|---|
| `cve_ent` | `CHAR(2)` FK |
| `variable_id` | `TINYINT` FK |
| `anio` | `SMALLINT` |
| `mes` | `TINYINT` |
| `valor` | `DECIMAL(10,3)` |
| `fuente_id` | `TINYINT` FK |

PK: `(cve_ent, variable_id, anio, mes, fuente_id)`.

### `clima_sitio_mensual`

Clima derivado por sitio.

| Columna | Tipo | Notas |
|---|---|---|
| `sitio_id` | `INT` FK | |
| `variable_id` | `TINYINT` FK | |
| `anio`, `mes` | | |
| `valor` | `DECIMAL(10,3)` | |
| `metodo` | `VARCHAR(20)` | `NEAREST` / `IDW` |
| `n_estaciones` | `TINYINT` | estaciones usadas |
| `fecha_calculo` | `DATETIME2(0)` | |

PK: `(sitio_id, variable_id, anio, mes, metodo)`.

---

## 7. Demografía

Tres tablas con el mismo diseño, una por nivel:

- `demografia_municipio` → PK `(cvegeo, anio, indicador_id, fuente_id)`.
- `demografia_localidad` → PK `(cve_loc, anio, indicador_id, fuente_id)`.
- `demografia_ageb` → PK `(cve_ageb, anio, indicador_id, fuente_id)`.

Columnas: `valor DECIMAL(18,4)`, `fuente_id`, `fecha_carga`.

El indicador se guarda en el nivel donde se publica. No se fuerza a todos los
indicadores a AGEB ni a municipio.

---

## 8. Vistas

### `vw_clima_mensual_vigente`

Una fila por `(estacion_id, variable_id, anio, mes)`. Ordena por:

1. `origen = 'OFICIAL'` primero.
2. `fecha_carga` más reciente.

Es la vista que deben consumir los reportes.

### `vw_clima_mensual_geo`

La vista vigente con nombres de entidad, municipio, localidad y variable.

### `vw_sitio_geografia`

Sitios con su jerarquía geográfica y banderas de asignación.

### `vw_sitio_clima_mensual`

Clima mensual de cada sitio contra sus `k` estaciones vecinas (incluye ranking,
distancia y peso).

### `vw_sitio_clima_cercano`

Solo `ranking = 1`.

### `vw_clima_hist_compat`

Reconstruye el formato ancho de `dbo.clima_hist` (`FECHA`, `Estado`, `Año`,
`Mes`, `Precipitacion`, `Tmax`, `Tmed`, `Tmin`, `Tdiff`) desde
`vw_clima_estatal_vigente`. Sirve para migrar reportes existentes sin cambiar
consultas de inmediato.

### `vw_clima_estatal_vigente`

Una fila por entidad-variable-año-mes. Prioriza `SMN_RED_CSV` (red reducida)
y usa `PDF_ESTATAL` solo si falta el mes. Es la base de
`vw_clima_hist_compat`.

---

## 9. Compatibilidad con `dbo.clima_hist`

- `dbo.clima_hist` **se actualiza de forma incremental para 2023+**: el ETL
  solo agrega meses posteriores al último que ya existe, o completa el último
  si está incompleto. **No reescribe** 2023+ en cada corrida ni toca
  1985–2022.
- `carga_inicial/sql/05_migrar_clima_hist.sql` copia sus filas a `clima_estatal_mensual`
  como `PDF_ESTATAL`, de forma idempotente, **solo para 2023 en adelante**.
- `actualizacion/load_estatal_csv.py` es la fuente **operativa**: descarga la
  red reducida mensual del SMN (CSV), agrega por entidad y carga
  `clima_estatal_mensual` con `fuente_id = SMN_RED_CSV`. El DAG
  `datos_publicos_estatal_csv` corre a diario con `--auto` y llama a
  `actualizacion/sync_clima_hist.py` para escribir el mes nuevo en
  `dbo.clima_hist`.
- `actualizacion/load_estatal_pdf.py` queda como **legacy/opcional** para la
  tabla estatal oficial exacta desde PDFs; su DAG vive en `legacy_dags/` y no
  se monta en Airflow. También sincroniza `clima_hist` de forma incremental.
- `actualizacion/sync_clima_hist.py` mantiene la tabla legacy: agrega meses
  nuevos, completa el último incompleto y respeta 1985–2022. `--recalcular`
  reescribe explícitamente un rango.
- `vw_clima_estatal_vigente` prioriza `SMN_RED_CSV` y usa `PDF_ESTATAL` solo
  si falta el mes. `vw_clima_hist_compat` se apoya en esa vista para
  reproducir el esquema antiguo (2023+).
- Si más adelante quieres retirar `clima_hist`, primero valida que todos los
  reportes usen la vista de compatibilidad o las tablas nuevas.
- El proceso legacy externo que truncaba `clima_hist` debe retirarse: ahora
  este ETL es el que la mantiene.

---

## 10. Índices

- Espaciales en `entidad`, `municipio`, `localidad`, `ageb`,
  `estacion` y `sitio`.
- Únicos filtrados en `clave_smn` y `clave_sih` (permiten varios `NULL`).
- `clima_diario (variable_id, fecha)` con `INCLUDE`.
- `clima_mensual (variable_id, anio, mes)` con `INCLUDE`.
- Índices por `cvegeo` en estaciones y sitios.
- Índices por `(anio, indicador_id)` en las tres tablas demográficas.

---

## 11. Decisiones de diseño

| Decisión | Motivo |
|---|---|
| Sin prefijo | nombres limpios en `dbo`; convive con `clima_hist` |
| `origen` + `fuente_id` en la PK mensual | permitir calculado y oficial a la vez |
| AGEB en tabla separada y opcional | no todos los proyectos necesitan ese detalle |
| Demografía por nivel | cada fuente publica en niveles distintos |
| `GEOGRAPHY` en SQL Server | consultas espaciales nativas (`STIntersects`, `STDistance`) |
| Fechas UTC en bitácora | comparación consistente entre servidores |
| Sin tablas de staging permanentes | el staging se crea y se destruye en cada `upsert` |
