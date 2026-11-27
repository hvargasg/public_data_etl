# Fuentes de datos

Este documento describe de dónde sale cada dato, con qué frecuencia se publica,
qué cubre y en qué tabla del modelo se guarda. Las URLs son patrones: los
códigos concretos se sustituyen al momento de la carga.

> **Enlaces oficiales consolidados:** los portales, las fichas de producto, los
> ZIP/XLSX directos y ejemplos verificados están en
> [`enlaces.md`](enlaces.md).

> **Ventana de carga:** el modelo almacena únicamente datos de clima desde
> **2023-01-01**. Las fuentes cubren más historia, pero el ETL ignora todo lo
> anterior a 2023. La demografía se conserva en su edición más reciente
> (Censo 2020, CONEVAL/CONAPO), porque no existe una fuente demográfica 2023+.

> **Importante:** las fuentes públicas cambian sin aviso. El ETL guarda la
> `fecha_carga` y el `fecha_corte`/emisión cuando la fuente lo declara, para que
> puedas auditar qué versión se usó.

---

## 1. Resumen

| Código (`fuente`) | Fuente | Frecuencia | Nivel | Tabla destino |
|---|---|---|---|---|
| `SMN_TXT_MENSUAL` | SMN, estadística mensual por estación | Mensual | Estación-mes | `clima_mensual` (OFICIAL) |
| `SMN_TXT_DIARIO` | SMN, registro diario (el modelo carga 2023+) | Diaria | Estación-día | `clima_diario` |
| `SIH_CSV_DIARIO` | SIH, CSV diario por estación | Irregular/semanal | Estación-día | `clima_diario` |
| `SMN_RED_CSV` | SMN, resumen mensual de red reducida | Mensual | Estación-mes | (opcional) `clima_mensual` |
| `PDF_ESTATAL` | CONAGUA, PDF estatal mensual | Mensual | Entidad-mes | `clima_estatal_mensual` |
| `CALCULO_PROPIO` | Agregación propia | A demanda | Estación-mes | `clima_mensual` (CALCULADO) |
| `INEGI_MG` | INEGI, Marco Geoestadístico | Anual | Entidad/municipio/localidad/AGEB | `entidad`, `municipio`, `localidad`, `ageb` |
| `INEGI_CENSO` | INEGI, Censo de Población y Vivienda | Decenal | Municipio/localidad/AGEB | `demografia_*` |
| `CONEVAL_IRS` | CONEVAL, Índice de Rezago Social | Irregular | Municipio/localidad/AGEB | `demografia_*` |
| `CONAPO_IM` | CONAPO, Índice de Marginación | Irregular | Municipio/localidad/AGEB | `demografia_*` |
| `CONAPO_PROY` | CONAPO, proyecciones de población | Irregular | Municipio | `demografia_municipio` |
| `DENUE` | INEGI, directorio de unidades económicas | Semestral | Punto → municipio/AGEB | `demografia_*` (agregado) |

Todas las tablas destino viven en **`DataLake.datos_publicos`**.

---

## 2. SMN — Servicio Meteorológico Nacional

### 2.1 Índice de estaciones (GeoJSON)

Descarga directa:
[estaciones_climatologicas.geojson](https://smn.conagua.gob.mx/tools/GUI/estaciones-climatologicas/data/estaciones_climatologicas.geojson)

Portal de información climatológica:
<https://smn.conagua.gob.mx/es/climatologia/informacion-climatologica/informacion-estadistica-climatologica>

- Aproximadamente **5,500 estaciones**.
- Propiedades: `clave`, `nombre`, `estado`, `municipio`, `organismo`, `cuenca`,
  `tipo`, `altitud`, `inicio`, `mas_reciente`, `situacion`, `diarios`,
  `mensuales`, `extremos`, `normales_*`.
- Coordenadas en WGS84 (longitud, latitud).
- Alimenta `datos_publicos.estacion` y de ahí se derivan las URLs de descarga.

El campo `clave` (5 dígitos) es la **clave SMN**. No confundirla con la clave
del SIH, que es alfanumérica y distinta.

### 2.2 TXT mensual por estación

Patrón:
`https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/{edo}/mes{clave}.txt`

Ejemplo verificado:
[mes01001.txt (Aguascalientes)](https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/ags/mes01001.txt)

- `{edo}` es una abreviatura de 3 letras minúsculas (CDMX usa `df`):
  `ags`, `bc`, `bcs`, `camp`, `coah`, `col`, `chis`, `chih`, `df`, `dgo`, `gto`,
  `gro`, `hgo`, `jal`, `mex`, `mich`, `mor`, `nay`, `nl`, `oax`, `pue`, `qro`,
  `qroo`, `slp`, `sin`, `son`, `tab`, `tamps`, `tlax`, `ver`, `yuc`, `zac`.
- Codificación UTF-8.
- Cabecera con `ESTACIÓN`, `NOMBRE`, `ESTADO`, `MUNICIPIO`, `SITUACIÓN`,
  `LATITUD`, `LONGITUD`, `ALTITUD` y la fecha de `EMISIÓN`.
- Después vienen bloques por variable. Cada bloque tiene un título, una fila de
  encabezado `AÑO  ENE FEB ... DIC  ACUM PROM MESES` y una fila por año.

Bloques que se cargan:

| Título del bloque | Variable |
|---|---|
| `LLUVIA TOTAL MENSUAL` | `PREC` |
| `EVAPORACIÓN MENSUAL` | `EVAP` |
| `TEMPERATURA MÁXIMA PROMEDIO` | `TMAX` |
| `TEMPERATURA MÍNIMA PROMEDIO` | `TMIN` |
| `TEMPERATURA MEDIA MENSUAL` | `TMED` |

Bloques que **no** se cargan: `LLUVIA MÁXIMA 24 H.`, `TEMPERATURA MÁXIMA
EXTREMA`, `TEMPERATURA MÍNIMA EXTREMA`, y las filas de resumen
`MÍNIMA/MÁXIMA/MEDIA/DESV.ST`.

Cada celda vacía significa "sin dato". Cada fila de año trae además el número
de meses con dato (`MESES`), que **no** equivale a días con dato.

- Frecuencia: **mensual**; el archivo se reescribe y puede corregir años
  anteriores. Por eso la carga es idempotente por rango y fuente.
- Se guarda como `origen='OFICIAL'`, `estado='DEFINITIVO'`.
- `fecha_corte` = fecha de emisión declarada en el archivo.
- `dias_con_dato` y `completo` quedan en `NULL`: el TXT mensual no informa
  cuántos días contribuyeron a cada mes. La completitud real solo se conoce con
  los diarios y la calcula `build_mensual` para las filas `CALCULADO`.

### 2.3 TXT diario por estación

Patrón:
`https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Diarios/{edo}/dia{clave}.txt`

Ejemplo verificado:
[dia01001.txt (Aguascalientes)](https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Diarios/ags/dia01001.txt)

- Misma cabecera de metadatos.
- Tabla con columnas `FECHA`, `PRECIP`, `EVAP`, `TMAX`, `TMIN` (no incluye
  `TMED`).
- Los faltantes se representan como `NULO`; se omiten al cargar.
- La fuente cubre desde finales del siglo XIX en algunas estaciones, pero el
  modelo solo carga desde 2023-01-01.
- Frecuencia: **diaria**, aunque el archivo completo se descarga y se filtra
  por rango.
- Se guarda en `clima_diario` con `fuente_id = SMN_TXT_DIARIO`.

### 2.4 Otros productos del SMN

- **Extremos**: patrón `.../Med-Extr/{edo}/medex{clave}.txt`.
  Ejemplo: [medex01001.txt](https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Med-Extr/ags/medex01001.txt).
- **Normales 1991-2020**: patrón `.../Normales9120/{edo}/nor9120_{clave}.txt`.
  Ejemplo: [nor9120_01001.txt](https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Normales9120/ags/nor9120_01001.txt).
- **Red reducida mensual (CSV)**:
  `https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/{AAAAMM}010000{TMax|TMed|TMin|Lluv}.csv`.
  Ejemplo: [202501010000TMax.csv](https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/202501010000TMax.csv).
  Cubre 2013 en adelante, ~1,400 estaciones y es **estación-mes**.
- **PDFs estatales**:
  `https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/{TMAX|TMED|TMIN|PREC}/{año}.pdf`.
  Ejemplo: [TMAX/2025.pdf](https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/TMAX/2025.pdf).
  Cubre 1985 en adelante y es **estado-mes** con las cuatro variables.

Página oficial para elegir el año:
<https://smn.conagua.gob.mx/es/climatologia/temperaturas-y-lluvias/resumenes-mensuales-de-temperaturas-y-lluvias>

> La ruta de los PDFs lleva acentos codificados (`Climatolog%C3%ADa` y
> `Pron%C3%B3stico%20clim%C3%A1tico`). Sin ellos el servidor devuelve error 500.

#### Red reducida CSV frente a PDFs estatales

El visor de la página oficial tiene un botón **“Descarga de Datos”** que baja
la red reducida en CSV; la tabla estado-mes que se muestra en la página
**solo** existe como PDF (no hay CSV/XLSX/JSON de esa tabla).

| Criterio | Red reducida CSV | PDF estatal |
|---|---|---|
| Grano | estación-mes | estado-mes |
| Cobertura | 2013+ | 1985+ |
| Variables | TMax, TMed, TMin, Lluv | TMAX, TMED, TMIN, PREC |
| Formato | CSV (UTF-8 o latin-1) | PDF (tabla) |
| `fuente_id` | `SMN_RED_CSV` | `PDF_ESTATAL` |
| Uso actual | **operativo** | legacy/opcional |

Diferencias medidas (2023–2026, media simple de estaciones por estado):

- **Temperatura:** ±0.3 °C; prácticamente idéntica al PDF.
- **Lluvia:** ~5–25% de diferencia, porque la red de lluvia es distinta.
  Ejemplos: México jul-2024 −21%, CDMX jul-2025 +19%, Sonora jul-2025 −20%.

Por eso el ETL usa la red reducida CSV como fuente operativa:

- `actualizacion/load_estatal_csv.py` descarga los CSV, agrega por entidad y
  carga `clima_estatal_mensual` con `fuente_id = SMN_RED_CSV`. Con `--auto`
  revisa a diario el mes anterior y se vuelve no-op cuando ya está cargado.
- `actualizacion/sync_clima_hist.py` escribe el mes nuevo en `dbo.clima_hist`
  de forma **incremental**: solo agrega meses posteriores al último que ya
  existe, o completa el último si está incompleto. No reescribe 2023+ en cada
  corrida.
- `vw_clima_estatal_vigente` prioriza el CSV y usa `PDF_ESTATAL` solo si falta
  el mes.
- `actualizacion/load_estatal_pdf.py` queda como **legacy/opcional** para
  obtener la tabla estatal oficial exacta; su DAG vive en `legacy_dags/` y no
  se monta en Airflow.

Los productos que aún no se cargan (extremos, normales y red reducida a nivel
estación) se pueden agregar como fuentes nuevas sin cambiar el modelo.

---

## 3. SIH — Sistema de Información Hidrológica

Portal: <https://sih.conagua.gob.mx/>

Patrón del CSV diario por estación:
`https://sih.conagua.gob.mx/basedatos/Climas/{CLAVE}.csv`

- Catálogo de ~7,500 estaciones; la clave es alfanumérica (por ejemplo,
  `AGSAG`), distinta de la clave SMN.
- Encabezados **heterogéneos** entre estaciones y años. El ETL los normaliza
  (minúsculas, sin acentos) y busca tokens como `precipitacion`, `evap`,
  `tempmax`, `tempmin`, `tempamb`/`tempmedia`.
- Puede venir en UTF-8 o Latin-1; se corrige mojibake típico.
- Frecuencia real: **irregular**. Muchas estaciones no tienen años recientes.
- Se guarda en `clima_diario` con `fuente_id = SIH_CSV_DIARIO`.
- Prioridad para el cálculo mensual: **SIH por encima de SMN diario** cuando
  ambos tienen el mismo día (ver [agregaciones.md](agregaciones.md)).

> El SIH está detrás de un WAF que puede devolver una página HTML con
> JavaScript en lugar del CSV (redirecciones 307 en bucle). Si eso ocurre,
> descarga los CSV manualmente y usa
> `python -m actualizacion.load_clima_sih --archivo-dir data/sih` con archivos
> `{clave}.csv`. El loader detecta respuestas HTML y lo reporta como error en
> lugar de intentar parsearlas.

> El SIH no siempre distingue `TMED`: cuando aparece `TempAmb`, se interpreta
> como temperatura media (`TMED`).

---

## 4. INEGI — Marco Geoestadístico

Producto: **Marco Geoestadístico 2025** (se actualiza cada año).

- Ficha del producto:
  <https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551163061>
- Programa:
  <https://www.inegi.org.mx/programas/mg/>
- Descarga integrada nacional 2025 (ZIP, ≈245 MB):
  <https://www.inegi.org.mx/contenidos/productos/prod_serv/contenidos/espanol/bvinegi/productos/geografia/marcogeo/794551163061/mg_2025_integrado.zip>

### 4.1 Empaquetado integrado nacional

Archivo: `mg_2025_integrado.zip` (≈245 MB).

Capas relevantes:

| Capa | Contenido | Campos clave |
|---|---|---|
| `00ent` | entidades federativas | `CVEGEO` (2), `CVE_ENT`, `NOMGEO` |
| `00mun` | municipios | `CVEGEO` (5), `CVE_ENT`, `CVE_MUN`, `NOMGEO` |
| `00l` | localidades (urbanas y rurales) | `CVEGEO` (9), `CVE_ENT`, `CVE_MUN`, `CVE_LOC`, `NOMGEO`, `AMBITO` |
| `00a` | AGEB urbanas y rurales | `CVE_ENT`, `CVE_MUN`, `CVE_LOC`, `CVE_AGEB`, `CVEGEO`, `AMBITO` |

`00l` y `00a` son polígonos. `00a` incluye:

- **AGEB urbana**: `CVEGEO` de 13 caracteres =
  `cve_ent(2) + cve_mun(3) + cve_loc(4) + cve_ageb(4)`.
- **AGEB rural**: `CVEGEO` de 9 caracteres =
  `cve_ent(2) + cve_mun(3) + cve_ageb(4)`, sin localidad.

El código de AGEB puede ser alfanumérico (por ejemplo, `216A`).

### 4.2 Empaquetado por entidad

También se puede descargar por estado. Los shapefiles suelen llamarse
`00ent`, `01mun`, `02loc`, `03ageb` (o equivalentes). El cargador reconoce
ambos empaquetados y concatena varias capas si apuntas a una carpeta que
contiene varios estados.

> Descarga los paquetes por entidad desde la ficha del producto:
> <https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551163061>

### 4.3 Claves que usa el modelo

| Nivel | Columna | Longitud | Composición |
|---|---|---|---|
| Entidad | `cve_ent` | 2 | `CVE_ENT` |
| Municipio | `cvegeo` | 5 | `cve_ent + cve_mun` |
| Localidad | `cve_loc` | 9 | `cvegeo + cve_loc(4)` |
| AGEB urbana | `cve_ageb` | 13 | `cve_loc + cve_ageb(4)` |
| AGEB rural | `cve_ageb` | 9 | `cvegeo + cve_ageb(4)` |

### 4.4 Frecuencia y versionado

- Frecuencia: **anual**.
- Cada tabla guarda `version_mg` (por ejemplo, `2025`).
- Al cambiar de versión, recarga con `--reload` y conserva la versión anterior
  en respaldo si necesitas comparar.

---

## 5. INEGI — Censo de Población y Vivienda

- Programa: <https://www.inegi.org.mx/programas/ccpv/2020/>
- Datos abiertos del Censo 2020:
  <https://www.inegi.org.mx/programas/ccpv/2020/#datos_abiertos>
- Descarga masiva del INEGI:
  <https://www.inegi.org.mx/app/descarga/default.html>
- Frecuencia: **decenal** (con conteos intermedios).
- Niveles: municipio, localidad y AGEB.
- Indicadores típicos: población total, hombres, mujeres, edad mediana, grupos
  de edad, viviendas, hogares, escolaridad, PEA.
- Se cargan con `carga_inicial/load_demografia.py` después de registrarlos en
  `datos_publicos.indicador`.

> Los productos censales por AGEB suelen venir en Excel o CSV con una fila por
> clave y una columna por indicador. Usa `--formato ancho --anio 2020`.

---

## 6. CONEVAL — Índice de Rezago Social

- Índice de Rezago Social 2020:
  <https://www.coneval.org.mx/Medicion/IRS/Paginas/Indice_Rezago_Social_2020.aspx>
- Portal CONEVAL: <https://www.coneval.org.mx/>
- Frecuencia: **irregular** (ediciones por año de medición).
- Niveles: municipio, localidad y AGEB, según la edición.
- Indicadores: índice de rezago social, grado, carencias (educación, salud,
  servicios, vivienda), población vulnerable.
- Se registran como indicadores `SOCIO` en `indicador`.

---

## 7. CONAPO — Marginación y proyecciones

- Portal CONAPO: <https://www.gob.mx/conapo>
- Datos abiertos CONAPO:
  <https://conapo.segob.gob.mx/es/CONAPO/Datos_abiertos>
- Índices de marginación 2020 (ficha):
  <https://www.gob.mx/conapo/documentos/indices-de-marginacion-2020-284372>
- Marginación municipal 2020 (XLSX):
  <https://conapo.segob.gob.mx/work/models/CONAPO/Datos_Abiertos/Municipio/IMM_2020.xlsx>
- Proyecciones 2020-2070 (ficha):
  <https://www.gob.mx/conapo/documentos/bases-de-datos-de-la-conciliacion-demografica-1950-a-2019-y-proyecciones-de-la-poblacion-de-mexico-2020-a-2070>
- Proyecciones 2020-2070 (ZIP):
  <https://conapo.segob.gob.mx/work/models/CONAPO/pry23/DB/ConDem50a19_ProyPob20a70.zip>

- **Índice de Marginación**: municipal, localidad y AGEB (según edición).
- **Proyecciones de población**: municipal, por edad y sexo, con horizonte a
  varias décadas.
- Frecuencia: **irregular**.
- Útil para denominadores poblacionales anuales entre censos.

---

## 8. INEGI — DENUE

- Programa: <https://www.inegi.org.mx/programas/denue/>
- Descarga masiva (incluye DENUE):
  <https://www.inegi.org.mx/app/descarga/default.html>
- Frecuencia: **semestral**.
- Unidades económicas con coordenadas; se pueden agregar a municipio o AGEB
  con un cruce espacial y guardar el conteo como indicador económico.
- Requiere un paso de agregación previo (no se carga punto por punto en las
  tablas demográficas).

---

## 9. Licencias y atribución

- Datos abiertos de CONAGUA/SMN/SIH: cita la fuente y la fecha de consulta.
- INEGI: usa los términos de libre uso de la información estadística y
  geográfica; cita INEGI y la versión del Marco Geoestadístico.
- CONEVAL y CONAPO: cita el programa y la edición.
- **Nivel socioeconómico AMAI**: requiere licencia de la Asociación Mexicana de
  Agencias de Investigación de Mercado; no se distribuye con este modelo.

---

## 10. Puntos frágiles conocidos

1. **SMN reescribe archivos**: un mes puede cambiar de valor entre emisiones.
   Recalcular con `--reload` o cargar de nuevo el rango.
2. **Faltantes como `NULO` o celda vacía**: el ETL los omite; no los convierte
   en cero.
3. **Lluvia estatal de PDFs**: no es reproducible con la red reducida pública.
   No la uses como verdad absoluta para municipios.
4. **Claves SIH vs SMN**: son catálogos distintos; el cruce se hace por
   coordenadas y nombre, no por clave.
5. **AGEB rural**: su clave es de 9 caracteres y no tiene localidad; no la
   fuerces a un `cve_loc`.
6. **Cambios de municipio**: entre versiones del MG puede haber
   reclasificaciones. Conserva `version_mg` y documenta el cambio.
7. **Cobertura desigual**: no todas las estaciones tienen todos los años ni
   todas las variables.
