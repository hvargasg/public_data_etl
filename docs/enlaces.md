# Enlaces oficiales de descarga

Este documento concentra los enlaces oficiales de las fuentes que usa el
modelo. Los enlaces se verificaron el **26 de noviembre de 2026**. Las fuentes
públicas cambian sin aviso: si un enlace directo falla, entra al portal o ficha
del producto y busca la versión vigente.

> Los ETL usan **patrones** con marcadores como `{edo}`, `{clave}`, `{anio}` o
> `{AAAAMM}`. En las tablas de abajo se muestra el patrón y un ejemplo real.
>
> **Ventana del modelo:** aunque estas fuentes cubren más historia, el ETL solo
> almacena datos de clima desde **2023-01-01** a la fecha. La demografía se
> conserva en su edición más reciente.

---

## 1. CONAGUA / SMN

### 1.1 Portal de información climatológica

- Información estadística climatológica:
  <https://smn.conagua.gob.mx/es/climatologia/informacion-climatologica/informacion-estadistica-climatologica>
- Resúmenes mensuales de temperaturas y lluvia:
  <https://smn.conagua.gob.mx/es/climatologia/temperaturas-y-lluvias/resumenes-mensuales-de-temperaturas-y-lluvias>

### 1.2 Índice de estaciones (GeoJSON)

| Recurso | Enlace |
|---|---|
| GeoJSON de estaciones | <https://smn.conagua.gob.mx/tools/GUI/estaciones-climatologicas/data/estaciones_climatologicas.geojson> |

El GeoJSON trae `clave`, `nombre`, `estado`, `municipio`, `latitud/longitud`,
`altitud`, `situacion`, `inicio`, `mas_reciente` y las URLs de descarga de cada
estación (`mensuales`, `diarios`, `extremos`, `normales_*`).

### 1.3 TXT mensual y diario por estación

| Recurso | Patrón | Ejemplo verificado |
|---|---|---|
| Mensual | `https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/{edo}/mes{clave}.txt` | <https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/ags/mes01001.txt> |
| Diario | `https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Diarios/{edo}/dia{clave}.txt` | <https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Diarios/ags/dia01001.txt> |
| Extremos | `https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Med-Extr/{edo}/medex{clave}.txt` | <https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Med-Extr/ags/medex01001.txt> |
| Normales 1991-2020 | `https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Normales9120/{edo}/nor9120_{clave}.txt` | <https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Normales9120/ags/nor9120_01001.txt> |

`{clave}` es la clave SMN de **5 dígitos** (por ejemplo, `01001`).

`{edo}` es la abreviatura de 3 letras minúsculas que usa el SMN:

```
ags  bc   bcs  camp coah col  chis chih df   dgo  gto  gro
hgo  jal  mex  mich mor  nay  nl   oax  pue  qro  qroo slp
sin  son  tab  tamps tlax ver yuc  zac
```

> La CDMX usa `df`, no `cdmx`.

### 1.4 Red reducida mensual (CSV)

| Recurso | Patrón | Ejemplo verificado |
|---|---|---|
| Temperatura máxima | `https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/{AAAAMM}010000TMax.csv` | <https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/202501010000TMax.csv> |
| Temperatura media | `.../{AAAAMM}010000TMed.csv` | <https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/202501010000TMed.csv> |
| Temperatura mínima | `.../{AAAAMM}010000TMin.csv` | <https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/202501010000TMin.csv> |
| Lluvia | `.../{AAAAMM}010000Lluv.csv` | <https://smn.conagua.gob.mx/tools/RESOURCES/com_archivo_datos_resumenes/202501010000Lluv.csv> |

Cobertura: 2013 en adelante y ~1,400 estaciones.

### 1.5 PDFs estatales mensuales

| Recurso | Patrón | Ejemplo verificado |
|---|---|---|
| Temperatura máxima | `https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/TMAX/{anio}.pdf` | <https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/TMAX/2025.pdf> |
| Temperatura media | `.../TMED/{anio}.pdf` | <https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/TMED/2025.pdf> |
| Temperatura mínima | `.../TMIN/{anio}.pdf` | <https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/TMIN/2025.pdf> |
| Precipitación | `.../PREC/{anio}.pdf` | <https://smn.conagua.gob.mx/tools/DATA/Climatolog%C3%ADa/Pron%C3%B3stico%20clim%C3%A1tico/Temperatura%20y%20Lluvia/PREC/2025.pdf> |

> La ruta real lleva acentos codificados (`Climatolog%C3%ADa` y
> `Pron%C3%B3stico%20clim%C3%A1tico`). Sin esos acentos el servidor devuelve
> error 500.

Página oficial para elegir el año:
<https://smn.conagua.gob.mx/es/climatologia/temperaturas-y-lluvias/resumenes-mensuales-de-temperaturas-y-lluvias>

### 1.6 SIH — Sistema de Información Hidrológica

| Recurso | Enlace |
|---|---|
| Portal SIH | <https://sih.conagua.gob.mx/> |
| CSV diario por estación | `https://sih.conagua.gob.mx/basedatos/Climas/{CLAVE}.csv` |

La clave del SIH es alfanumérica y distinta de la clave SMN. El sitio puede
estar protegido por un WAF; en ese caso descarga los CSV manualmente y usa
`python -m actualizacion.load_clima_sih --archivo-dir data/sih`.

---

## 2. INEGI

### 2.1 Marco Geoestadístico

| Recurso | Enlace |
|---|---|
| Ficha del Marco Geoestadístico 2025 | <https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551163061> |
| Programa Marco Geoestadístico | <https://www.inegi.org.mx/programas/mg/> |
| Tema Marco Geoestadístico | <https://www.inegi.org.mx/temas/mg/> |
| Descarga integrada nacional 2025 (ZIP, ≈245 MB) | <https://www.inegi.org.mx/contenidos/productos/prod_serv/contenidos/espanol/bvinegi/productos/geografia/marcogeo/794551163061/mg_2025_integrado.zip> |

El ZIP integrado contiene:

- `00ent.shp` — entidades.
- `00mun.shp` — municipios.
- `00l.shp` — localidades.
- `00a.shp` — AGEB urbanas y rurales.

También existen paquetes por entidad. El cargador reconoce ambos formatos.

### 2.2 Censo de Población y Vivienda 2020

| Recurso | Enlace |
|---|---|
| Programa Censo 2020 | <https://www.inegi.org.mx/programas/ccpv/2020/> |
| Datos abiertos del Censo 2020 | <https://www.inegi.org.mx/programas/ccpv/2020/#datos_abiertos> |
| Portal de descarga masiva del INEGI | <https://www.inegi.org.mx/app/descarga/default.html> |
| Datos abiertos del INEGI | <https://www.inegi.org.mx/servicios/datosabiertos.html> |

### 2.3 DENUE

| Recurso | Enlace |
|---|---|
| Programa DENUE | <https://www.inegi.org.mx/programas/denue/> |
| Descarga masiva (incluye DENUE) | <https://www.inegi.org.mx/app/descarga/default.html> |

---

## 3. CONEVAL

| Recurso | Enlace |
|---|---|
| Índice de Rezago Social 2020 | <https://www.coneval.org.mx/Medicion/IRS/Paginas/Indice_Rezago_Social_2020.aspx> |
| Portal CONEVAL | <https://www.coneval.org.mx/> |

La página del IRS concentra las bases por entidad, municipio, localidad y AGEB,
según la edición.

---

## 4. CONAPO

| Recurso | Enlace |
|---|---|
| Portal CONAPO | <https://www.gob.mx/conapo> |
| Datos abiertos CONAPO | <https://conapo.segob.gob.mx/es/CONAPO/Datos_abiertos> |
| Índices de marginación 2020 (ficha) | <https://www.gob.mx/conapo/documentos/indices-de-marginacion-2020-284372> |
| Marginación municipal 2020 (XLSX) | <https://conapo.segob.gob.mx/work/models/CONAPO/Datos_Abiertos/Municipio/IMM_2020.xlsx> |
| Proyecciones 2020-2070 (ficha) | <https://www.gob.mx/conapo/documentos/bases-de-datos-de-la-conciliacion-demografica-1950-a-2019-y-proyecciones-de-la-poblacion-de-mexico-2020-a-2070> |
| Proyecciones 2020-2070 (ZIP) | <https://conapo.segob.gob.mx/work/models/CONAPO/pry23/DB/ConDem50a19_ProyPob20a70.zip> |

La ficha de marginación incluye las bases por entidad, municipio, localidad y
AGEB. Las proyecciones incluyen población, defunciones, nacimientos, migración
y tasas específicas.

---

## 5. AMAI — Nivel Socioeconómico

| Recurso | Enlace |
|---|---|
| AMAI | <https://www.amai.org/> |

El sitio puede rechazar clientes automatizados (HTTP 406); ábrelo en un
navegador. El NSE AMAI por AGEB **requiere licencia** de la Asociación Mexicana
de Agencias de Investigación de Mercado. No se distribuye con este modelo.

---

## 6. Cómo verificar un enlace

Desde Linux/macOS:

```bash
curl -sIL "https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/ags/mes01001.txt" \
  | grep -iE "HTTP/|content-type|content-length"
```

Desde PowerShell:

```powershell
Invoke-WebRequest -Method Head -Uri "https://www.inegi.org.mx/programas/mg/"
```

Señales de que un enlace cambió:

- `301` o `302` con `Location` a otra ruta: sigue la redirección con `curl -L`.
- `404`: la ruta o la clave ya no existe.
- `500`: el servidor no resolvió la ruta (suele pasar con acentos no
  codificados).
- `Content-Type: text/html` cuando esperabas un TXT/CSV/PDF: probablemente te
  devolvieron una página de error o un portal.

---

## 7. Notas de vigencia

- El Marco Geoestadístico se publica **cada año**; la versión 2025 es la usada
  en este modelo. Si sale una nueva, actualiza `--version` y recarga.
- Los TXT del SMN se reescriben: un mes puede corregirse en una emisión
  posterior.
- El SIH cambia con frecuencia y puede estar detrás de un WAF.
- Las ediciones de CONEVAL y CONAPO son irregulares; conserva el año de la
  edición en `demografia_*`.
- Los enlaces directos a archivos pueden incluir un identificador de producto
  (`upc`) que cambia entre versiones. Si el ZIP directo falla, entra a la ficha
  del producto y descarga desde ahí.
