# public_data_etl
descarga datos publicos del SNM y del SIH, ademas de datos del INEGI


Carpeta autocontenida para crear en `DataLake.datos_publicos` un conjunto de tablas
homologadas con claves oficiales del INEGI (`cve_ent`, `cvegeo`, `cve_loc`,
`cve_ageb`), cargar datos climáticos de CONAGUA/SMN/SIH y construir **tu propia
serie mensual** sin depender de que el SMN o el SIH publiquen a tiempo.

La tabla histórica `dbo.clima_hist` **no se modifica**: el modelo nuevo convive
con ella y ofrece una vista de compatibilidad con el mismo formato.

**Ventana de datos:** el modelo solo carga y calcula clima desde
**2023-01-01** a la fecha. No almacena el histórico anterior.

**Base de datos destino:** `DataLake`, schema `datos_publicos`. El runner
`--init` aplica las tablas ahí; si la base o el schema no existieran, los crea.

---

## 1. Dos bloques operativos

La lógica está separada en dos carpetas para que sea evidente qué se corre una
vez y qué se corre todos los días o todos los meses.

| Carpeta | Cuándo se usa | Contenido |
|---|---|---|
| **`carga_inicial/`** | una vez, o de forma ocasional (anual, decenal, cuando cambian claves o sitios) | estructuras SQL, geografía INEGI, estaciones, sitios, puente sitio-estación, demografía, migración de `clima_hist` |
| **`actualizacion/`** | diario, mensual o recurrente | carga de clima SMN/SIH, construcción de la serie mensual propia, clima de sitios, runners y queries de control |
| **`comun/`** | siempre | configuración, constantes de vigencia, conexión a SQL Server, utilidades de parseo y `upsert` |

La regla es simple:

- Si **crea o cambia la estructura** o **actualiza catálogos/claves**, va en
  `carga_inicial/`.
- Si **carga datos nuevos del clima** o **recalcula series**, va en
  `actualizacion/`.

---

## 2. Estructura de carpetas

```
public_data_etl/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── .dockerignore
├── Makefile
├── data/
├── comun/
│   ├── __init__.py
│   ├── config.py
│   ├── constants.py
│   ├── db.py
│   └── utils.py
├── carga_inicial/
│   ├── README.md
│   ├── __init__.py
│   ├── run_inicial.py
│   ├── backfill_clima.py
│   ├── load_inegi.py
│   ├── load_estaciones.py
│   ├── load_sitios.py
│   ├── match_sitio_estacion.py
│   ├── load_demografia.py
│   └── sql/
│       ├── 00_crear_base.sql
│       ├── 00_crear_schema.sql
│       ├── 00_verificar_nombres.sql
│       ├── 01a_catalogos.sql
│       ├── 01b_geografia.sql
│       ├── 01c_estaciones_sitios.sql
│       ├── 01d_hechos_clima.sql
│       ├── 01e_demografia.sql
│       ├── 02_indices.sql
│       ├── 03_vistas.sql
│       ├── 04_catalogos.sql
│       ├── 05_migrar_clima_hist.sql
│       ├── 06_purgar_antes_2023.sql
│       └── 99_drop.sql
├── actualizacion/
│   ├── README.md
│   ├── __init__.py
│   ├── run_diario.py
│   ├── run_mensual.py
│   ├── run_query.py
│   ├── load_clima_smn.py
│   ├── load_clima_sih.py
│   ├── load_claves_geo.py
│   ├── build_clima_clientes.py
│   ├── build_mensual.py
│   ├── sql/
│   │   ├── 10_claves_geo_dbo.sql
│   │   └── 11_clima_clientes.sql
│   └── queries/
│       ├── README.md
│       ├── 01_vigente.sql
│       ├── 02_comparativo_oficial.sql
│       ├── 03_cobertura_diaria.sql
│       ├── 04_calidad_datos.sql
│       └── 05_sitios_clima.sql
├── dags/
│   ├── .airflowignore
│   ├── etl_common.py
│   ├── datos_publicos_diario_dag.py
│   ├── datos_publicos_mensual_dag.py
│   ├── datos_publicos_claves_geo_dag.py
│   ├── datos_publicos_clima_clientes_dag.py
│   └── datos_publicos_historico_dag.py
├── scripts/
│   ├── etl-infisical.sh
│   └── etl-helpers.sh
└── docs/
    ├── fuentes.md
    ├── enlaces.md
    ├── modelo.md
    ├── agregaciones.md
    ├── ageb.md
    ├── clima_clientes.md
    └── operacion.md
```

---

## 3. Requisitos

- SQL Server 2016 SP1 o superior (se usan `CREATE OR ALTER VIEW`, `EOMONTH`,
  `DATEFROMPARTS`, índices espaciales y columnas `GEOGRAPHY`).
- Python 3.10 o superior.
- Driver ODBC de SQL Server (17 u 18).
- Para `carga_inicial/load_inegi.py`: `geopandas`, `shapely` y `pyproj`.
- Docker (opcional, recomendado en el servidor): el repo incluye una imagen con
  el driver ODBC y todas las dependencias (ver [sección 13](#13-contenedor-makefile-e-infisical)).

```bash
cd homologado_db
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

---

## 4. Configuración

Las credenciales **no van en el código**. Copia el ejemplo y completa el `.env`:

```bash
cp .env.example .env
```

```dotenv
DB_SERVER=servidor\instancia
DB_NAME=DataLake
DB_SCHEMA=datos_publicos
DB_USER=usuario
DB_PASSWORD=<tu_contraseña>
DB_DRIVER=ODBC Driver 18 for SQL Server
```

`comun/config.py` lee esas variables en este orden:

1. Variables ya presentes en el entorno del proceso.
2. Archivo indicado por `ETL_ENV_FILE` (lo usan los contenedores y los DAGs).
3. `.env` de la raíz del proyecto (desarrollo local).

Si falta `DB_SERVER`, `DB_USER` o `DB_PASSWORD`, el ETL se detiene con un
mensaje claro. En el servidor los secretos no viven en `.env`: los entrega
Infisical (ver [sección 13](#13-contenedor-makefile-e-infisical)).

---

## 5. Puesta en marcha (una vez)

### 5.1 Crear base, estructuras y catálogos

```bash
python -m carga_inicial.run_inicial --init
```

El runner asegura la base `DataLake` y el schema `datos_publicos` (si no
existen, los crea; la base se crea conectándose a `master` en autocommit) y
después aplica, en orden, `carga_inicial/sql/`:

1. `01a_catalogos.sql` — variables, fuentes, indicadores, bitácora.
2. `01b_geografia.sql` — entidad, municipio, localidad, AGEB.
3. `01c_estaciones_sitios.sql` — estaciones, sitios y puente.
4. `01d_hechos_clima.sql` — diario, mensual, estatal, sitio.
5. `01e_demografia.sql` — hechos demográficos por nivel.
6. `02_indices.sql` — índices espaciales y de consulta.
7. `03_vistas.sql` — vistas de consulta y compatibilidad.
8. `04_catalogos.sql` — semillas de variables, fuentes e indicadores.

Si la base ya existe y el usuario no tiene permiso de `CREATE DATABASE`, usa:

```bash
python -m carga_inicial.run_inicial --init --sin-crear-base
```

Si el schema ya existe y no tienes permiso de `CREATE SCHEMA`:

```bash
python -m carga_inicial.run_inicial --init --sin-crear-base --sin-crear-esquema
```

También puedes crear la base con `carga_inicial/sql/00_crear_base.sql`
(conectado a `master`) y el schema con
`carga_inicial/sql/00_crear_schema.sql` (conectado a `DataLake`).

Para migrar `dbo.clima_hist` (opcional e idempotente, solo 2023+):

```bash
python -m carga_inicial.run_inicial --migrar
```

### 5.2 Cargar geografía del INEGI

Descarga y descomprime el Marco Geoestadístico 2025 (el paquete integrado
nacional sirve; trae `00ent`, `00mun`, `00l` y `00a`):

```bash
python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --version 2025 --reload
# o solo algunas entidades
python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --entidades 01,06 --reload
# sin AGEB (más rápido y ligero)
python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --skip-ageb --reload
```

El cargador reconoce también el empaquetado por entidad
(`00ent/01mun/02loc/03ageb`) y concatena varias capas si apuntas a una carpeta
con varios estados.

### 5.3 Cargar estaciones del SMN

```bash
python -m carga_inicial.load_estaciones
```

Descarga el GeoJSON de estaciones (≈5,500), inserta/actualiza
`datos_publicos.estacion` y, si ya existe geografía, cruza cada estación con
municipio, localidad y AGEB.

### 5.4 Cargar sitios propios (opcional)

```bash
python -m carga_inicial.load_sitios --archivo data/sitios.csv
```

El archivo debe tener al menos `id`, `lat` y `lon`; opcionalmente `nombre` y
`altitud`. Se aceptan CSV y Excel.

### 5.5 Emparejar sitios con estaciones

```bash
python -m carga_inicial.match_sitio_estacion --k 5
```

Genera `datos_publicos.sitio_estacion` con las `k` estaciones más cercanas, distancia,
diferencia de altitud y peso IDW normalizado.

### 5.6 Carga de clima 2023 a la fecha (una vez)

La ventana vigente es **2023-01-01 a la fecha**. El ETL ignora el histórico
anterior.

```bash
# Diarios + mensual oficial + serie mensual propia
python -m carga_inicial.backfill_clima

# o solo una parte
python -m carga_inicial.backfill_clima --tipo diario
python -m carga_inicial.backfill_clima --tipo mensual
```

También puedes ejecutar los pasos por separado:

```bash
python -m actualizacion.load_clima_smn --tipo diario --desde 2023-01-01
python -m actualizacion.load_clima_smn --tipo mensual
python -m actualizacion.build_mensual --desde 2023-01 --hasta 2025-12
```

Si ya tienes datos viejos cargados, purga una vez:

```bash
python -m carga_inicial.run_inicial --purgar
```

Después de esta carga inicial, el día a día se opera con
`actualizacion/run_diario.py` y el mes con `actualizacion/run_mensual.py`.

### 5.7 Cargar demografía (opcional)

```bash
python -m carga_inicial.load_demografia \
  --nivel municipio --archivo data/censo_municipio.csv \
  --anio 2020 --fuente INEGI_CENSO --formato auto
```

---

## 6. Operación recurrente

> En el servidor estos mismos flujos se ejecutan con los DAGs de la
> [sección 14](#14-orquestación-con-airflow) o con `make diario` /
> `make mensual`. Los comandos de esta sección sirven para ejecución local o
> para depurar un paso por separado.

### 6.1 Diario

```bash
python -m actualizacion.run_diario
```

Carga los diarios recientes del SMN, opcionalmente los del SIH (`--sih`) y
recalcula la serie mensual propia de los meses tocados.

```bash
python -m actualizacion.run_diario --dias 7
python -m actualizacion.run_diario --sih --dias 30
python -m actualizacion.run_diario --desde 2025-01-01 --hasta 2025-01-31
```

### 6.2 Mensual

```bash
python -m actualizacion.run_mensual
```

Carga el TXT mensual oficial del SMN (por defecto, año actual y anterior;
ventana mínima 2023) y recalcula la serie propia. Opciones:

```bash
python -m actualizacion.run_mensual --desde 2025 --hasta 2025
python -m actualizacion.run_mensual --completo   # 2023 a la fecha
python -m actualizacion.run_mensual --solo-calculo --desde 2025-01 --hasta 2025-12
```

### 6.3 Consultas

```bash
python -m actualizacion.run_query --archivo actualizacion/queries/01_vigente.sql
python -m actualizacion.run_query --archivo actualizacion/queries/04_calidad_datos.sql
```

Ver `actualizacion/queries/README.md` para el catálogo completo.

Para DML/DDL (por ejemplo, cerrar un `carga_log` colgado), agrega `--ejecutar`:
hace `commit` y no intenta imprimir filas.

```bash
python -m actualizacion.run_query --archivo ruta/al/script.sql --ejecutar
```

### 6.4 Claves geográficas de negocio

Rellena `cvegeo` (municipio) y `cve_ent` (estado) en `dbo.Clientes` y
`dbo.CEDIS` a partir de sus coordenadas, usando el Marco Geoestadístico de
`DataLake.datos_publicos`.

```bash
python -m actualizacion.load_claves_geo                 # ambas tablas
python -m actualizacion.load_claves_geo --tabla clientes
python -m actualizacion.load_claves_geo --tabla cedis
python -m actualizacion.load_claves_geo --tabla clientes --limite 2000   # prueba
python -m actualizacion.load_claves_geo --batch 5000    # filas por lote (default)
```

Reglas:

* **Solo rellena lo que está en `NULL`**; nunca sobrescribe una clave ya
  asignada. Por eso la corrida diaria solo procesa los registros nuevos.
* `cve_ent` se deriva de `LEFT(cvegeo, 2)` cuando hubo municipio.
* Si el punto cae en México pero fuera de todo municipio, se usa el polígono de
  `entidad` para obtener al menos `cve_ent`.
* Si la coordenada es inválida (fuera del bounding box de México o `0,0`), se
  usa el texto `Estado` y, si hace falta, `Ciudad` (solo para `cve_ent`).
* El cálculo geométrico se hace **en SQL Server** con los índices espaciales de
  `municipio` y `entidad`; Python solo orquesta por lotes (default 5,000 filas)
  para no abrir transacciones largas ni bloquear `dbo`.

Las columnas se crean de forma idempotente con
`actualizacion/sql/10_claves_geo_dbo.sql`. `dbo.Clientes` se actualiza por
`(Cliente_id, Direccion_id)` y `dbo.CEDIS` por su PK `CEDIS`.

En el servidor se ejecuta con `make claves-geo` (acepta `ARGS="..."`) y el DAG
diario de las 02:00 (ver [sección 14](#14-orquestación-con-airflow)).

### 6.5 Clima derivado de clientes

Asigna clima mensual a cada ubicación de `dbo.Clientes` a partir de las
estaciones OPERANDO más cercanas. **No** guarda clima diario por cliente: usa
celdas de ~1 km, un puente con k=5 estaciones y un hecho mensual derivado
(`NEAREST` e `IDW`).

```bash
python -m actualizacion.build_clima_clientes                 # últimos 2 meses
python -m actualizacion.build_clima_clientes --todo           # 2023 a la fecha
python -m actualizacion.build_clima_clientes --desde 2025-01 --hasta 2025-12
python -m actualizacion.build_clima_clientes --recalcular-puente
python -m actualizacion.build_clima_clientes --sin-mensual --limite 200
```

- `cliente_ubicacion`: celdas de ~1 km (`ROUND(Lat,2)`, `ROUND(Lon,2)`).
- `cliente_ubicacion_map`: domicilio → celda.
- `cliente_estacion`: k=5 estaciones vecinas con distancia, altitud y peso IDW.
- `clima_cliente_mensual`: resultado mensual por celda, variable y método.

El puente se refresca solo cada 30 días; `--recalcular-puente` lo fuerza. El
clima mensual se lee de `vw_clima_mensual_vigente` (oficial gana). Para el
detalle diario están las vistas `vw_clima_cliente_diario` y
`vw_clima_cliente_diario_cercano`.

Decisiones, mediciones y limitaciones completas en
[`docs/clima_clientes.md`](docs/clima_clientes.md). En el servidor se ejecuta
con `make clima-clientes` y el DAG diario de las 03:00.

---

## 7. Tablas principales

| Tabla | Grano | Uso |
|---|---|---|
| `entidad` | entidad | polígono y nombre oficial |
| `municipio` | municipio (`cvegeo`) | polígono y nombre oficial |
| `localidad` | localidad (`cve_loc`) | polígono y ámbito |
| `ageb` | AGEB (`cve_ageb`, opcional) | detalle urbano |
| `estacion` | estación SMN/SIH | coordenadas, claves, URLs |
| `sitio` | punto propio | coordenadas y geografía asignada |
| `sitio_estacion` | sitio-estación | vecinos y peso IDW |
| `cliente_ubicacion` | celda de ~1 km | ubicaciones únicas de clientes |
| `cliente_ubicacion_map` | domicilio | enlace cliente-domicilio → celda |
| `cliente_estacion` | celda-estación | k=5 vecinas y peso IDW |
| `clima_diario` | estación-variable-fecha-fuente | observaciones diarias |
| `clima_mensual` | estación-variable-mes-origen-fuente | calculado y oficial |
| `clima_estatal_mensual` | entidad-variable-mes | serie de PDFs/migración |
| `clima_sitio_mensual` | sitio-variable-mes-método | clima derivado |
| `clima_cliente_mensual` | celda-variable-mes-método | clima derivado de clientes |
| `demografia_municipio` | municipio-año-indicador | demografía/social |
| `demografia_localidad` | localidad-año-indicador | demografía/social |
| `demografia_ageb` | AGEB-año-indicador | demografía/social fina |

Todas las tablas viven en **`DataLake.datos_publicos`**.

Las tablas de negocio `dbo.Clientes` y `dbo.CEDIS` se enriquecen con `cvegeo`
(municipio) y `cve_ent` (estado) usando esta geografía; ver
[sección 6.4](#64-claves-geográficas-de-negocio). Las ubicaciones de
`dbo.Clientes` también reciben clima mensual derivado; ver
[sección 6.5](#65-clima-derivado-de-clientes).

Detalle completo del modelo estrella (dimensiones, hechos, puente y por qué no
hay redundancia) en [`docs/modelo.md`](docs/modelo.md).

---

## 8. ¿Hace falta AGEB?

No para arrancar. **Entidad + municipio + localidad** es el denominador común
de casi todas las fuentes públicas y cubre clima, demografía básica y reportes.
AGEB es una capa **opcional** útil cuando el análisis es urbano y necesitas
detalle de colonia: población y edad por AGEB, rezago social intraurbano,
marginación o nivel socioeconómico AMAI (este último con licencia).

En el modelo, `ageb` y `sitio.cve_ageb` son opcionales y nullables. Si
un punto no cae en una AGEB, el sitio sigue funcionando por localidad o
municipio. Recomendación completa y consultas de ejemplo en
[`docs/ageb.md`](docs/ageb.md).

---

## 9. Calculado y oficial a la vez

`clima_mensual` permite dos filas para el mismo
`estacion_id + variable_id + anio + mes`:

- `origen = 'CALCULADO'`, `estado = 'PRELIMINAR'`, fuente `CALCULO_PROPIO`.
- `origen = 'OFICIAL'`, `estado = 'DEFINITIVO'`, fuente `SMN_TXT_MENSUAL`.

La vista `datos_publicos.vw_clima_mensual_vigente` devuelve **una fila por periodo**:
si existe la oficial, gana; si no, usa la calculada. Así puedes seguir
operando con tu cálculo y, cuando el SMN publique, la consulta cambia sola sin
perder el registro propio.

Reglas completas en [`docs/agregaciones.md`](docs/agregaciones.md).

---

## 10. Documentación

| Documento | Contenido |
|---|---|
| [`docs/fuentes.md`](docs/fuentes.md) | origen, URL, cobertura y frecuencia de cada fuente |
| [`docs/enlaces.md`](docs/enlaces.md) | **enlaces oficiales de descarga**, fichas de producto, ZIP/XLSX y ejemplos verificados |
| [`docs/modelo.md`](docs/modelo.md) | tablas, llaves, relaciones y vistas |
| [`docs/agregaciones.md`](docs/agregaciones.md) | reglas diaria → mensual, prioridad y completitud |
| [`docs/ageb.md`](docs/ageb.md) | cuándo usar AGEB y cómo cruzarla |
| [`docs/clima_clientes.md`](docs/clima_clientes.md) | clima derivado de clientes: decisiones, tablas, cálculo y operación |
| [`docs/operacion.md`](docs/operacion.md) | runbook, validaciones y solución de problemas |
| [`carga_inicial/README.md`](carga_inicial/README.md) | detalle del bloque de carga inicial |
| [`actualizacion/README.md`](actualizacion/README.md) | detalle del bloque recurrente y queries |

---

## 11. Enlaces oficiales

Los enlaces oficiales de descarga están consolidados y verificados en
[`docs/enlaces.md`](docs/enlaces.md). Accesos principales:

| Fuente | Enlace |
|---|---|
| Estaciones SMN (GeoJSON) | <https://smn.conagua.gob.mx/tools/GUI/estaciones-climatologicas/data/estaciones_climatologicas.geojson> |
| SMN, ejemplo TXT mensual | <https://smn.conagua.gob.mx/tools/RESOURCES/Normales_Climatologicas/Mensuales/ags/mes01001.txt> |
| SMN, resúmenes mensuales (PDFs) | <https://smn.conagua.gob.mx/es/climatologia/temperaturas-y-lluvias/resumenes-mensuales-de-temperaturas-y-lluvias> |
| SIH | <https://sih.conagua.gob.mx/> |
| INEGI, Marco Geoestadístico 2025 (ZIP) | <https://www.inegi.org.mx/contenidos/productos/prod_serv/contenidos/espanol/bvinegi/productos/geografia/marcogeo/794551163061/mg_2025_integrado.zip> |
| INEGI, Censo 2020 | <https://www.inegi.org.mx/programas/ccpv/2020/> |
| CONEVAL, IRS 2020 | <https://www.coneval.org.mx/Medicion/IRS/Paginas/Indice_Rezago_Social_2020.aspx> |
| CONAPO, datos abiertos | <https://conapo.segob.gob.mx/es/CONAPO/Datos_abiertos> |
| AMAI (NSE, requiere licencia) | <https://www.amai.org/> |

El detalle de patrones, cobertura, ejemplos verificados y notas de vigencia
está en [`docs/enlaces.md`](docs/enlaces.md).

---

## 12. Seguridad y buenas prácticas

- No escribas credenciales en `.py`, `.sql` ni documentación.
- Mantén `.env` fuera del control de versiones (ya está en `.gitignore`).
- Usa un usuario de base de datos con permisos mínimos sobre el schema
  `datos_publicos`.
- `carga_inicial/sql/99_drop.sql` elimina **todas** las tablas del schema
  `datos_publicos`; úsalo solo en desarrollo.
- Antes de una recarga masiva, respalda `dbo.clima_hist` y las tablas de
  `datos_publicos`.

---

## 13. Contenedor, Makefile e Infisical

El repo incluye una imagen Docker y un `Makefile` para ejecutar el ETL sin
instalar el driver ODBC ni las dependencias de geografía en el host. La imagen
se llama `public-data-etl:latest` e incluye `comun/`, `carga_inicial/` y
`actualizacion/`.

### 13.1 Construir la imagen

```bash
make build
# equivalente:
docker build -t public-data-etl:latest .
```

La carpeta `data/` **no** viaja dentro de la imagen: se monta en
`/app/data` al ejecutar el contenedor. Así puedes pasar archivos como
`--mg-dir data/mg_2025` o `--sitios data/sitios.csv` usando las mismas rutas
relativas que en local.

### 13.2 Resolución de secretos: `.env` o Infisical

`scripts/etl-infisical.sh` es el wrapper que ejecuta un módulo dentro de la
imagen y resuelve los secretos de dos formas:

| Modo | Cuándo | Origen de los secretos |
| --- | --- | --- |
| `env` | Desarrollo | `.env` del repositorio (montado en `/run/secrets/etl_env`) |
| `infisical` | Servidor | carpeta `/datos_publicos_etl` del entorno `prod` |

El modo se elige solo (`auto`): si existe `/etc/infisical/machine.env` usa
Infisical; si no, `.env`. Se puede forzar con
`SECRETS_SOURCE=env|infisical`, en el entorno o en `.env`.

```bash
# Desarrollo: usa .env y ./data
make diario ARGS="--dias 7"
make mensual ARGS="--solo-calculo --desde 2026-11 --hasta 2026-11"
make inicial ARGS="--init"
make backfill ARGS="--tipo diario"
make claves-geo ARGS="--tabla ambas"
make clima-clientes ARGS="--todo"
make query QUERY=04_calidad_datos.sql

# Servidor: machine.env es root:640, por eso sudo
sudo make diario ARGS="--dias 7"
sudo make check-infisical

# Un módulo cualquiera (sin target específico)
make etl MODULO=carga_inicial.load_estaciones ARGS=""
make etl MODULO=carga_inicial.load_inegi ARGS="--mg-dir data/mg_2025 --reload"
```

En modo Infisical el wrapper:

1. Lee `machine.env` (por defecto `/etc/infisical/machine.env`).
2. Hace login con Universal Auth, sin imprimir credenciales.
3. Exporta la carpeta `INFISICAL_PATH` (por defecto `/datos_publicos_etl`).
4. Comprueba que estén `DB_SERVER`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`.
5. Convierte el JSON de Infisical a líneas `KEY=valor` (sin comillas) y ejecuta
   el contenedor con `--env-file` desde un archivo temporal con permisos `600`,
   que se borra al terminar.

El host necesita `jq` para esa conversión. Docker `--env-file` no elimina las
comillas que agrega el formato `dotenv` de Infisical.

Variables reconocidas por el wrapper: `ETL_MODULO`, `SECRETS_SOURCE`,
`INFISICAL_MACHINE_FILE`, `INFISICAL_ENV`, `INFISICAL_PATH`, `ETL_IMAGE`,
`ETL_DATA`, `ETL_UID` y `ETL_DOCKER_NETWORK` (opcional; vacía = red por
defecto). Este ETL no depende de lakeFS: solo necesita salida a Internet hacia
SMN, SIH e INEGI.

### 13.3 Machine Identity y `machine.env`

Si el servidor ya usa Infisical para Airflow, el archivo ya existe. Si no:

```bash
sudo install -d -m 700 /etc/infisical
sudo install -m 640 /dev/null /etc/infisical/machine.env
sudo editor /etc/infisical/machine.env
```

Contenido:

```dotenv
INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=<client-id>
INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET=<client-secret>
INFISICAL_API_URL=http://127.0.0.1:8081
INFISICAL_PROJECT_ID=<project-id>
```

Debe quedar como `root:root` y modo `640`, por eso los comandos del wrapper se
ejecutan con `sudo`. Si tu CLI necesita el sufijo `/api`, usa
`INFISICAL_API_URL=http://127.0.0.1:8081/api`.

La identity necesita permiso de lectura sobre la carpeta `/datos_publicos_etl` del
entorno `prod`. Para validar login y secretos sin tocar la base de datos:

```bash
sudo make check-infisical
```

### 13.4 Secretos que deben existir en Infisical

| Secreto | Obligatorio | Uso |
|---|---|---|
| `DB_SERVER` | Sí | Host o IP del servidor SQL Server (admite `servidor\instancia`). |
| `DB_NAME` | Sí | Base de datos. Por defecto: `DataLake`. |
| `DB_USER` | Sí | Usuario de SQL Server. |
| `DB_PASSWORD` | Sí | Contraseña del usuario. |
| `DB_SCHEMA` | No | Schema destino. Por defecto: `datos_publicos`. |
| `DB_DRIVER` | No | Driver ODBC. Por defecto: `ODBC Driver 18 for SQL Server`. |
| `DB_ENCRYPT` | No | `Encrypt`. Por defecto: `yes`. |
| `DB_TRUST_CERT` | No | `TrustServerCertificate`. Por defecto: `yes`. |

### 13.5 Comandos del `Makefile`

| Comando | Descripción |
| --- | --- |
| `make help` | Muestra los objetivos disponibles. |
| `make env` | Crea `.env` desde `.env.example` (no sobrescribe). |
| `make check` | Compila `comun/`, `carga_inicial/`, `actualizacion/` y `dags/`, y revisa las CLI. |
| `make build` | Construye `public-data-etl:latest`. |
| `make diario ARGS="..."` | Ejecuta `actualizacion.run_diario` con `.env` o Infisical. |
| `make mensual ARGS="..."` | Ejecuta `actualizacion.run_mensual`. |
| `make inicial ARGS="..."` | Ejecuta `carga_inicial.run_inicial`. |
| `make backfill ARGS="..."` | Ejecuta `carga_inicial.backfill_clima`. |
| `make claves-geo ARGS="..."` | Rellena `cvegeo`/`cve_ent` en `dbo.Clientes` y `dbo.CEDIS`. |
| `make clima-clientes ARGS="..."` | Deriva clima mensual para las ubicaciones de clientes. |
| `make query QUERY=...` | Ejecuta una query de `actualizacion/queries/`. |
| `make etl MODULO=... ARGS="..."` | Ejecuta cualquier módulo del repo. |
| `make etl-infisical ...` | Fuerza el modo Infisical. |
| `make check-infisical` | Valida login y secretos de Infisical. |
| `make shell` | Abre una shell en la imagen con `./data` montado. |
| `make clean` | Borra las cachés `__pycache__`. |
| `make deploy` | Pull, reconstruye la imagen si hace falta y valida el ETL. |

En el servidor, si tu usuario no está en el grupo `docker`, usa
`make build DOCKER="sudo docker"`.

### 13.6 Despliegue con `make deploy`

`make deploy` deja la imagen lista para la siguiente corrida del DAG:

1. Falla si hay cambios locales sin commitear (`ALLOW_DIRTY=1` lo omite).
2. Ejecuta `git pull --ff-only origin main` (`BRANCH` y `REMOTE` configurables).
3. Calcula una huella de `Dockerfile`, `.dockerignore`, `comun/`,
   `carga_inicial/`, `actualizacion/`, `requirements.txt` y la arquitectura del
   host. Si cambió, o si la imagen no existe, reconstruye
   `public-data-etl:latest`.
4. Valida la imagen ejecutando `python -m actualizacion.run_diario --help`.
5. Guarda la huella en `/var/lib/public-data-etl-deploy/build-fingerprint`.
6. Muestra el commit desplegado y el ID de la imagen.

```bash
cd /opt/services/public_data_etl
sudo make deploy

# Forzar el pull aunque haya cambios locales sin commitear
sudo make deploy ALLOW_DIRTY=1
```

`make deploy` **no** ejecuta el ETL ni descarga datos: solo deja la imagen lista
para la siguiente corrida del DAG. Tampoco reinicia Airflow: los DAGs se montan
desde `dags/` y Airflow los recarga solo. Si cambió únicamente `dags/` no hay
build; si cambió el código, las dependencias o el `Dockerfile`, sí.

El nombre de la imagen debe coincidir con `IMAGEN_ETL` de `dags/etl_common.py`
(`public-data-etl:latest`). Si lo cambias en el `Makefile`, cámbialo también
allí.

### 13.7 Atajos para la terminal del servidor

```bash
source /opt/services/public_data_etl/scripts/etl-helpers.sh
```

| Atajo | Equivalente |
| --- | --- |
| `etl <opciones>` | Ejecuta el módulo indicado por `ETL_MODULO` (por defecto `actualizacion.run_diario`). |
| `diario <opciones>` | `actualizacion.run_diario`. |
| `mensual <opciones>` | `actualizacion.run_mensual`. |
| `inicial <opciones>` | `carga_inicial.run_inicial`. |
| `backfill <opciones>` | `carga_inicial.backfill_clima`. |
| `consulta <archivo.sql>` | `actualizacion.run_query --archivo ...`. |

`etl` reintenta con `sudo` si `machine.env` existe pero no es legible.

---

## 14. Orquestación con Airflow

Los DAGs usan la API de Airflow 3 (`airflow.sdk`), requieren el proveedor
`apache-airflow-providers-docker` y acceso al socket de Docker del host. Toda la
configuración compartida vive en `dags/etl_common.py`; los DAGs solo declaran su
horario y sus tareas.

| DAG | Disparo | Horario (America/Mexico_City) | Descripción |
|---|---|---|---|
| `datos_publicos_diario` | Automático | 06:00 | Carga los TXT diarios del SMN de los últimos 7 días y recalcula la serie mensual propia. |
| `datos_publicos_mensual` | Automático | Día 3 a las 07:00 | Carga el TXT oficial del SMN y recalcula la serie propia del rango de años. |
| `datos_publicos_claves_geo` | Automático | 02:00 | Rellena `cvegeo`/`cve_ent` en `dbo.Clientes` y `dbo.CEDIS` solo para filas nuevas. |
| `datos_publicos_clima_clientes` | Automático | 03:00 | Deriva clima mensual (NEAREST/IDW) para las ubicaciones de `dbo.Clientes` (k=5, últimos 2 meses). |
| `datos_publicos_historico_manual` | Manual | — | Carga histórica de clima 2023+ (`carga_inicial.backfill_clima`). |

Los DAGs de clima terminan con una tarea `etl_completo` (`EmptyOperator`) que
emite un Asset (`datos_publicos_diario_completo`,
`datos_publicos_mensual_completo` o `datos_publicos_backfill_completo`) solo si
la carga tuvo éxito. Otros DAGs o consumidores pueden usar esos Assets en su
`schedule`. `datos_publicos_claves_geo` no emite Asset: es un proceso
idempotente e independiente que solo depende de que existan las tablas de
negocio y la geografía INEGI cargada.

Las tareas usan `DockerOperator`; cada corrida arranca un contenedor
independiente de `public-data-etl:latest`, por lo que las dependencias del ETL
no se mezclan con las de Airflow.

### 14.1 Configuración en el host

La configuración se define una sola vez en `dags/etl_common.py` y asume las
siguientes rutas del EC2 (no del contenedor de Airflow):

```python
IMAGEN_ETL = "public-data-etl:latest"
REPO_HOST = os.getenv("ETL_REPO_HOST", "/opt/services/public_data_etl")
DATOS_HOST = f"{REPO_HOST}/data"
ENV_FILE_HOST = f"{REPO_HOST}/.env"
USUARIO_HOST = "1000:1000"
ZONA_HORARIA = "America/Mexico_City"
FECHA_INICIO = pendulum.datetime(2026, 1, 1, tz=ZONA_HORARIA)
```

Ajusta estas constantes según tu instalación, o define `ETL_REPO_HOST` en el
entorno de Airflow. La función `tarea_etl()` construye cada `DockerOperator` y:

* En local, monta `DATOS_HOST` → `/app/data` y `ENV_FILE_HOST` →
  `/run/secrets/etl_env` (solo lectura), con `ETL_ENV_FILE=/run/secrets/etl_env`.
* En el servidor, monta `DATOS_HOST` → `/app/data` y obtiene los secretos de
  Infisical al ejecutar cada tarea (ver abajo).

El usuario `1000:1000` debe coincidir con el propietario del directorio `data/`
en el host para evitar problemas de lectura de archivos auxiliares.

Cada tarea recibe por defecto `mem_limit="4g"` y un `execution_timeout` de dos
horas; `tarea_etl()` acepta argumentos adicionales (`**kwargs`) que se pasan al
`DockerOperator`, como `retries`, `trigger_rule` o `mem_limit`. La clase
`DockerOperatorSinPlantillas` desactiva la búsqueda de archivos de plantilla
(`template_ext = ()`), porque Airflow interpreta como plantilla cualquier texto
terminado en `.env`, `.sh` o `.bash` —incluido `/run/secrets/etl_env`— y
fallaría con `TemplateNotFound`. Las expresiones `{{ ... }}` siguen funcionando.

### 14.2 Secretos en producción (Infisical)

En el servidor, Airflow se levanta con el overlay `docker-compose.infisical.yaml`
del repo de Airflow. Ese overlay:

1. Monta `/etc/infisical/machine.env` en `/run/secrets/infisical/machine.env` y
   pone `AIRFLOW_SECRETS_FROM_INFISICAL=true` en el scheduler, el apiserver y el
   dag-processor.
2. Conecta esos servicios a la red externa de Infisical
   (`infisical-agacentro_default` por defecto).

La imagen de Airflow ya incluye el CLI de `infisical`, así que el DAG no agrega
dependencias al contenedor del ETL.

El DAG detecta ese modo y, **al ejecutar cada tarea** (no al parsear el DAG):

1. Hace login con Universal Auth usando `machine.env`.
2. Exporta los secretos de la carpeta `/datos_publicos_etl` (entorno `prod`).
3. Se los pasa solo al contenedor del ETL como variables de entorno. No monta
   `.env` ni deja las credenciales en el entorno general de Airflow.

En local no existe `machine.env`, así que el DAG sigue montando `.env` como
antes. La detección se puede forzar con `ETL_SECRETS_SOURCE=env|infisical`.

### 14.3 Variables de configuración del DAG

Se pueden definir en el entorno de Airflow (o en la carpeta `/airflow` de
Infisical):

| Variable | Por defecto | Descripción |
|---|---|---|
| `ETL_REPO_HOST` | `/opt/services/public_data_etl` | Ruta del repo en el host (datos y `.env`). |
| `ETL_SECRETS_SOURCE` | `auto` | `auto`, `env` o `infisical`. |
| `ETL_INFISICAL_PATH` | `/datos_publicos_etl` | Carpeta de secretos del ETL. |
| `ETL_INFISICAL_ENV` | `prod` | Entorno de Infisical. |
| `INFISICAL_MACHINE_FILE` | `/run/secrets/infisical/machine.env` | Ruta del `machine.env` dentro del contenedor (la define el overlay de Airflow). |
| `INFISICAL_CONTAINER_API_URL` | `http://infisical:8080` | URL de Infisical dentro de la red Docker. |
| `ETL_DOCKER_NETWORK` | vacío | Red Docker opcional para el contenedor del ETL. |

### 14.4 Puesta en marcha en el servidor

1. Crea la carpeta `/datos_publicos_etl` en el proyecto de Infisical, entorno
   `prod`, y carga los secretos de la tabla de la sección 13.4.
2. Verifica que la identity del servidor tenga acceso de lectura a esa carpeta.
3. Despliega el código con `sudo make deploy` (hace pull y reconstruye la imagen
   si cambió el código, las dependencias o el `Dockerfile`) y confirma que
   Airflow no reporta errores de importación:

   ```bash
   cd /opt/services/public_data_etl
   sudo make deploy

   cd /opt/services/airflow
   sudo ./scripts/compose.sh exec airflow-scheduler \
     airflow dags list-import-errors
   ```

4. Despausa `datos_publicos_diario`, `datos_publicos_mensual` y
   `datos_publicos_claves_geo`, y ejecuta una
   tarea de prueba desde la UI. Si falta un secreto, el log de la tarea indica
   exactamente cuál, sin imprimir valores.

> Los secretos se consultan en cada ejecución, así que un cambio en Infisical se
> usa en la siguiente corrida sin reiniciar Airflow. El `.env` del servidor ya no
> es necesario para los DAGs ni para las ejecuciones manuales: `make` y
> `scripts/etl-infisical.sh` usan la misma Machine Identity y la carpeta
> `/datos_publicos_etl`. Conserva `.env` solo para el modo `env` local.

> Para operaciones que no están en un DAG (crear estructuras, recargar
> geografía, cargar sitios o demografía) usa `make inicial`, `make etl` o los
> atajos de `scripts/etl-helpers.sh`; todos resuelven los secretos igual que los
> DAGs.

### 14.5 Montaje de los DAGs en Airflow

Airflow solo descubre los DAGs que están dentro de su carpeta
`/opt/airflow/dags`. El `dags/` de este repo no se copia a la imagen del ETL: se
monta como una **subcarpeta** del directorio de DAGs, igual que los demás
proyectos del servidor. En `/opt/services/airflow/docker-compose.yaml` agrega,
en el bloque `x-airflow-common` y en el servicio `airflow-scheduler`:

```yaml
- ${DATOS_PUBLICOS_DAGS_DIR:-/opt/services/public_data_etl/dags}:/opt/airflow/dags/datos_publicos:ro
```

Después recrea los servicios para que tomen el montaje y confirma el registro:

```bash
cd /opt/services/airflow
sudo ./scripts/compose.sh up -d
sudo docker exec airflow-airflow-scheduler-1 airflow dags list | grep datos_publicos
```

`dags/.airflowignore` excluye `etl_common.py`, para que Airflow no intente
parsearlo como un DAG. Los DAGs se importan desde el subdirectorio
`datos_publicos/` y comparten el helper `etl_common.py` que está junto a ellos.

