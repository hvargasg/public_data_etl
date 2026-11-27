# Operación

Guía para instalar, ejecutar y mantener el modelo homologado.

> Los enlaces oficiales de descarga (SMN, SIH, INEGI, CONEVAL, CONAPO) están
> consolidados y verificados en [`enlaces.md`](enlaces.md).

---

## 1. Requisitos

- SQL Server 2016 SP1 o superior con soporte de `GEOGRAPHY`.
- Python 3.10+.
- Driver ODBC de SQL Server 17 u 18.
- Permisos para crear tablas, vistas e índices en `datos_publicos`.
- Para `--init`, permiso `CREATE DATABASE` en `master` (o crear la base
  manualmente y usar `--sin-crear-base`).
- Para `carga_inicial/load_inegi.py`: `geopandas`, `shapely`, `pyproj`.

Verifica el driver:

```bash
python -c "import pyodbc; print(pyodbc.drivers())"
```

---

## 2. Instalación

```bash
cd homologado_db
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con el servidor, base, usuario y contraseña. **No** subas `.env` al
repositorio.

```dotenv
DB_SERVER=servidor\instancia
DB_NAME=DataLake
DB_SCHEMA=datos_publicos
DB_USER=usuario
DB_PASSWORD=<tu_contraseña>
```

La base `DataLake` y el schema `datos_publicos` se aseguran con
`run_inicial --init` (si ya existen, no se vuelven a crear). Si prefieres
crearlos antes, ejecuta `00_crear_base.sql` conectado a `master` y
`00_crear_schema.sql` conectado a `DataLake`. Si no tienes permiso de
`CREATE SCHEMA`, usa `--sin-crear-esquema`.

> **Nombres sin prefijo:** las tablas se llaman `variable`, `municipio`,
> `clima_diario`, `demografia_municipio`, etc., dentro de
> `DataLake.datos_publicos`. Los scripts no sobrescriben objetos existentes
> (`IF OBJECT_ID(...) IS NULL`). Si `DataLake.datos_publicos` ya tiene tablas
> con esos nombres, resuelve la colisión antes de `--init`.
> Preflight: `sqlcmd -S servidor -d DataLake -i carga_inicial/sql/00_verificar_nombres.sql`.
>
> Los archivos SQL usan el token `{{schema}}`. El runner lo reemplaza por
> `DB_SCHEMA` (`datos_publicos`). Si ejecutas un SQL manualmente, reemplaza el
> token por `datos_publicos`.

Prueba la conexión (después de crear la base y el schema):

```bash
python -c "from comun.db import get_engine; get_engine().connect(); print('OK')"
```

---

## 3. Carga inicial

El orden importa por las llaves foráneas. Todo esto vive en `carga_inicial/`.

```bash
# 1. Estructuras y catálogos
python -m carga_inicial.run_inicial --init

# 2. Geografía (descarga y descomprime el MG 2025 antes)
python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --version 2025 --reload

# 3. Estaciones del SMN (cruce espacial con la geografía ya cargada)
python -m carga_inicial.load_estaciones

# 4. Sitios propios (opcional)
python -m carga_inicial.load_sitios --archivo data/sitios.csv

# 5. Vecinos sitio-estación (opcional)
python -m carga_inicial.match_sitio_estacion --k 5

# 6. Demografía (opcional)
python -m carga_inicial.load_demografia \
  --nivel municipio --archivo data/censo_municipio.csv \
  --anio 2020 --fuente INEGI_CENSO

# 7. Migrar clima_hist (opcional, solo 2023+)
python -m carga_inicial.run_inicial --migrar
```

También puedes usar el runner para varias etapas:

```bash
python -m carga_inicial.run_inicial --init \
  --mg-dir /ruta/mg_2025 --sitios data/sitios.csv
```

La **carga inicial de clima** se hace una sola vez, con la ventana
**2023-01-01 a la fecha**:

```bash
python -m carga_inicial.backfill_clima
```

O por pasos, si prefieres control fino:

```bash
python -m actualizacion.load_clima_smn --tipo diario --desde 2023-01-01
python -m actualizacion.load_clima_smn --tipo mensual
python -m actualizacion.build_mensual --desde 2023-01 --hasta 2025-12
```

Si ya tienes datos anteriores a 2023, purga una vez:

```bash
python -m carga_inicial.run_inicial --purgar
```

---

## 4. Operación periódica

### 4.1 Diaria o semanal

```bash
python -m actualizacion.run_diario --dias 7

# incluyendo el SIH
python -m actualizacion.run_diario --sih --dias 30
```

El runner carga los diarios y recalcula los meses tocados. Si quieres control
fino, ejecuta los pasos por separado:

```bash
python -m actualizacion.load_clima_sih --dias 30
python -m actualizacion.load_clima_smn --tipo diario --desde 2025-01-01
python -m actualizacion.build_mensual --desde 2025-01 --hasta 2025-12
```

> Ajusta las fechas al periodo real. `build_mensual` solo borra y recrea las
> filas `CALCULADO` del rango indicado.

### 4.2 Mensual

```bash
python -m actualizacion.run_mensual
```

Por defecto carga el oficial del año actual y el anterior, y recalcula la serie
propia. La ventana mínima es 2023. Opciones:

```bash
python -m actualizacion.run_mensual --desde 2025 --hasta 2025
python -m actualizacion.run_mensual --completo   # 2023 a la fecha
python -m actualizacion.run_mensual --solo-calculo --desde 2025-01 --hasta 2025-12
```

Revisa la comparación calculado vs oficial ([agregaciones.md](agregaciones.md), sección 6)
y las queries de `actualizacion/queries/`.

### 4.3 Anual

- Nuevo Marco Geoestadístico:
  `python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --reload`.
- Revisar sitios que quedaron sin localidad o AGEB.
- Recargar demografía si hay nueva edición.

### 4.4 Decenal / irregular

- Censo: `python -m carga_inicial.load_demografia --nivel ... --anio ...`.
- CONEVAL / CONAPO: nueva edición, nuevo año.
- DENUE: agregar por AGEB o municipio y cargar el conteo.

---

## 5. Programación

### 5.1 Airflow (recomendado en el servidor)

El repo incluye DAGs para ejecutar el ETL en contenedores aislados:

| DAG | Horario (America/Mexico_City) |
|---|---|
| `datos_publicos_diario` | 06:00 todos los días |
| `datos_publicos_mensual` | día 3 a las 07:00 |
| `datos_publicos_historico_manual` | manual (carga 2023+) |

En el servidor los secretos los entrega Infisical al ejecutar cada tarea; en
local los DAGs montan el `.env` del repo. El detalle de configuración, imagen,
Makefile y variables está en
[`../README.md#14-orquestación-con-airflow`](../README.md#14-orquestación-con-airflow).

Las ejecuciones manuales también usan el mismo contenedor y los mismos
secretos:

```bash
make diario ARGS="--dias 7"
make mensual ARGS="--completo"
```

### 5.2 Linux (cron)

```cron
# Diario 06:00
0 6 * * * cd /opt/conagua/homologado_db && .venv/bin/python -m actualizacion.run_diario --dias 7 >> logs/diario.log 2>&1

# Mensual día 3 a las 07:00
0 7 3 * * cd /opt/conagua/homologado_db && .venv/bin/python -m actualizacion.run_mensual >> logs/mensual.log 2>&1
```

### 5.3 Windows (Programador de tareas)

- Acción: iniciar programa.
- Programa: `C:\ruta\homologado_db\.venv\Scripts\python.exe`.
- Argumentos: `-m actualizacion.run_mensual`.
- Iniciar en: `C:\ruta\homologado_db`.

---

## 6. Idempotencia y recargas

| Paso | Qué borra antes de insertar |
|---|---|
| `load_clima_smn --tipo mensual` | `OFICIAL` de `SMN_TXT_MENSUAL` por estación y rango de años |
| `load_clima_smn --tipo diario` | `SMN_TXT_DIARIO` por estación y rango de fechas |
| `load_clima_sih` | `SIH_CSV_DIARIO` por estación y rango de fechas |
| `build_mensual` | `CALCULADO` de `CALCULO_PROPIO` por rango |
| `build_mensual` (sitios) | `NEAREST`/`IDW` por rango |
| `load_inegi --reload` | geografía de las entidades seleccionadas (orden: AGEB → localidad → municipio → entidad) |
| `load_demografia` | no borra: hace `MERGE` por clave + año + indicador + fuente |

Las cargas de clima solo aceptan datos desde **2023-01-01**. Si indicas una
fecha anterior, el ETL la ajusta a esa ventana y lo avisa en consola.

Recomendaciones:

- No uses `--reload` en producción sin respaldo.
- Si recargas geografía, vuelve a ejecutar `load_estaciones` y
  `load_sitios` para reasignar claves. `--reload` limpia esas claves antes de
  borrar para respetar las llaves foráneas.
- Si ya cargaste demografía, `--reload` puede fallar porque esas tablas
  referencian municipio/localidad/AGEB. Exporta o limpia
  `demografia_*` del periodo/entidad antes de recargar y vuelve a cargarla
  después.
- Para corregir un mes, ejecuta el paso con el rango exacto.

---

## 7. Bitácora y monitoreo

Cada paso escribe en `datos_publicos.carga_log`.

```sql
SELECT TOP (50)
    carga_id, proceso, fuente_id, inicio, fin,
    DATEDIFF(SECOND, inicio, fin) AS segundos,
    filas, estado, mensaje
FROM datos_publicos.carga_log
ORDER BY carga_id DESC;
```

Errores recientes:

```sql
SELECT *
FROM datos_publicos.carga_log
WHERE estado = 'ERROR'
ORDER BY carga_id DESC;
```

Una carga que quedó `EN_PROCESO` sin `fin` probablemente murió por timeout o
corte de red; revisa el log del proceso y vuelve a ejecutar.

---

## 8. Validaciones después de cada carga

```sql
-- ¿Hay estaciones sin municipio?
SELECT COUNT(*) FROM datos_publicos.estacion WHERE cvegeo IS NULL;

-- ¿Hay sitios sin localidad?
SELECT COUNT(*) FROM datos_publicos.sitio WHERE cve_loc IS NULL;

-- ¿Hay meses calculados incompletos?
SELECT COUNT(*) FROM datos_publicos.clima_mensual
WHERE origen = 'CALCULADO' AND completo = 0;

-- ¿Hay datos anteriores a 2023? (debe ser 0)
SELECT 'diario' AS tabla, COUNT(*) AS filas
FROM datos_publicos.clima_diario WHERE fecha < '2023-01-01'
UNION ALL
SELECT 'mensual', COUNT(*) FROM datos_publicos.clima_mensual WHERE anio < 2023
UNION ALL
SELECT 'estatal', COUNT(*) FROM datos_publicos.clima_estatal_mensual WHERE anio < 2023
UNION ALL
SELECT 'sitio', COUNT(*) FROM datos_publicos.clima_sitio_mensual WHERE anio < 2023;

-- ¿Hay duplicados en la vista vigente? (debe ser 0)
SELECT COUNT(*) FROM (
    SELECT estacion_id, variable_id, anio, mes
    FROM datos_publicos.vw_clima_mensual_vigente
    GROUP BY estacion_id, variable_id, anio, mes
    HAVING COUNT(*) > 1
) x;

-- ¿Qué estaciones tienen más datos?
SELECT TOP (10) e.clave_smn, e.nombre, COUNT(*) AS filas
FROM datos_publicos.clima_diario d
JOIN datos_publicos.estacion e ON e.estacion_id = d.estacion_id
GROUP BY e.clave_smn, e.nombre
ORDER BY filas DESC;
```

---

## 9. Cómo extender el modelo

### 9.1 Nueva variable climática

1. Inserta en `datos_publicos.variable` con `agregacion` (`SUMA`/`MEDIA`).
2. Agrega el parseo en el loader correspondiente.
3. Si viene de una fuente nueva, insértala en `datos_publicos.fuente`.
4. Vuelve a correr `build_mensual`.

### 9.2 Nuevo indicador demográfico

1. Inserta en `datos_publicos.indicador` con `codigo`, `dominio` y `niveles`.
2. Carga el archivo con `load_demografia` usando ese `codigo` como nombre de
   columna (formato ancho) o valor de la columna indicador (formato largo).

### 9.3 Nueva fuente

1. Inserta en `datos_publicos.fuente`.
2. Crea un loader que use `log_carga` y `insert_rows`/`upsert`.
3. Documenta en [fuentes.md](fuentes.md).

---

## 10. Permisos sugeridos

Usuario ETL:

- `db_datareader`, `db_datawriter` sobre la base.
- `CREATE TABLE` solo si vas a ejecutar `--init` o `--reload`.
- `ALTER` sobre `datos_publicos` para crear vistas e índices.

Usuario de consulta:

- Solo `SELECT` sobre las tablas y vistas `*`.

---

## 11. Respaldo y recuperación

Antes de una carga masiva:

```sql
BACKUP DATABASE [DataLake]
TO DISK = N'/ruta/backup/DataLake_antes_etl.bak'
WITH INIT, COMPRESSION, STATS = 10;
```

Si algo sale mal:

1. Revisa `carga_log`.
2. Corrige el rango afectado y vuelve a ejecutar el paso (idempotente).
3. Si necesitas reiniciar todo: `carga_inicial/sql/99_drop.sql` y luego `--init`. **Solo en
   desarrollo.**
4. `dbo.clima_hist` no se modifica en ningún paso; úsala como referencia.

---

## 12. Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| `Faltan variables de entorno` | `.env` incompleto | completa `DB_SERVER`, `DB_USER`, `DB_PASSWORD` |
| `Data source name not found` | driver ODBC ausente | instala el driver 18 y ajusta `DB_DRIVER` |
| Error de certificado SSL | servidor con certificado autofirmado | `DB_ENCRYPT=yes` y `DB_TRUST_CERT=yes` |
| `The MERGE statement conflicted with the FOREIGN KEY` | geografía no cargada o clave inexistente | carga INEGI antes; revisa `cvegeo`/`cve_loc` |
| `Cannot insert duplicate key` en AGEB | dos AGEB con la misma clave | revisa `CVEGEO` y versión del MG |
| Estaciones sin municipio | no se cargó el MG o el punto cae fuera | carga geografía y vuelve a correr `load_estaciones` |
| Sitios sin localidad | punto rural o polígono ausente | revisa `sin_localidad`; usa municipio como respaldo |
| `String or binary data would be truncated` | nombre o URL más largo que la columna | amplía la columna o recorta el dato |
| Descarga SMN 404 | abreviatura de estado o clave incorrecta | usa la URL guardada en `estacion`; revisa [enlaces.md](enlaces.md) |
| PDF estatal 500 | ruta sin acentos codificados | usa el patrón de [enlaces.md](enlaces.md) (`Climatolog%C3%ADa/...`) |
| SIH devuelve HTML o 307 en bucle | WAF/JavaScript del SIH | descarga los CSV y usa `--archivo-dir data/sih` |
| Muchos `NULO` en diario | estación con cobertura intermitente | normal; revisa `dias_con_dato` |
| Datos anteriores a 2023 | carga vieja o migración de `clima_hist` | ejecuta `python -m carga_inicial.run_inicial --purgar` |
| Conflicto de nombres en `datos_publicos` | tabla ajena con nombre `variable`, `municipio`, etc. | ejecuta `00_verificar_nombres.sql` y renombra/mueve la tabla ajena antes de `--init` |
| `build_mensual` no genera filas | no hay diarios en el rango o `valor` es NULL | revisa `clima_diario` y el rango |
| Timeout al cargar AGEB | muchos polígonos | usa `--entidades` y carga por estado |
| Acentos corruptos | archivo Latin-1 | el ETL ya intenta corregir; si persiste, revisa la codificación de origen |

---

## 13. Rendimiento

- Carga la geografía por entidad si el volumen es alto:
  `load_inegi --entidades 01,06,...`.
- Ajusta `chunksize` en `insert_rows` si tu red es lenta.
- Los índices espaciales aceleran `STIntersects`/`STDistance`; no los elimines.
- Para reportes grandes, usa la vista vigente y filtra por `anio`/`variable`.
- Evita `SELECT *` sobre `clima_diario` en consultas interactivas.

---

## 14. Seguridad

- Credenciales solo en `.env` o variables de entorno del servicio.
- Usuario de base con permisos mínimos.
- No expongas la carpeta `data/` ni los respaldos en repositorios públicos.
- Revisa la licencia de cada fuente antes de redistribuir datos.
- `carga_inicial/sql/99_drop.sql` es destructivo; protégelo o no lo copies a producción.
