# Carga inicial y actualizaciones ocasionales

Este bloque se ejecuta **una vez** para dejar lista la base, y después solo
cuando cambie algo estructural:

- Versión nueva del Marco Geoestadístico del INEGI.
- Actualización del catálogo de estaciones del SMN.
- Altas, bajas o cambios de sitios propios.
- Nueva edición de censo, CONEVAL, CONAPO o DENUE.
- Reinstalación o migración de `dbo.clima_hist`.

**No** se usa para el día a día. Para eso está `actualizacion/`.

> Los enlaces oficiales de descarga están en
> [`../docs/enlaces.md`](../docs/enlaces.md).

---

## 1. Contenido

```
carga_inicial/
├── README.md
├── sql/
│   ├── 00_crear_base.sql
│   ├── 00_crear_schema.sql
│   ├── 00_verificar_nombres.sql
│   ├── 01a_catalogos.sql
│   ├── 01b_geografia.sql
│   ├── 01c_estaciones_sitios.sql
│   ├── 01d_hechos_clima.sql
│   ├── 01e_demografia.sql
│   ├── 02_indices.sql
│   ├── 03_vistas.sql
│   ├── 04_catalogos.sql
│   ├── 05_migrar_clima_hist.sql
│   ├── 06_purgar_antes_2023.sql
│   └── 99_drop.sql
├── run_inicial.py
├── backfill_clima.py
├── load_inegi.py
├── load_estaciones.py
├── load_sitios.py
├── match_sitio_estacion.py
└── load_demografia.py
```

---

## 2. Orden recomendado

La base destino es **`DataLake`**, schema **`datos_publicos`**. El primer
comando aplica las estructuras (y crea la base/schema si no existieran; usa
`--sin-crear-base` o `--sin-crear-esquema` si ya los tienes y no quieres
intentar `CREATE DATABASE`/`CREATE SCHEMA`).

> Los nombres de tabla son limpios, sin prefijo (`variable`, `municipio`,
> `clima_diario`, etc.), dentro de `DataLake.datos_publicos`. Los scripts usan
> `IF OBJECT_ID(...) IS NULL`, así que **no sobrescriben** tablas existentes.
> Si tu `DataLake.datos_publicos` ya tiene una tabla con alguno de esos nombres,
> revisa el conflicto antes de ejecutar `--init`.
>
> Preflight opcional:
> `sqlcmd -S servidor -d DataLake -i carga_inicial/sql/00_verificar_nombres.sql`
>
> Los SQL usan el token `{{schema}}`; el runner lo reemplaza por `DB_SCHEMA`.

```bash
# 1. Base + estructuras + catálogos
python -m carga_inicial.run_inicial --init

# 2. Geografía del INEGI
python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --version 2025 --reload

# 3. Catálogo de estaciones del SMN
python -m carga_inicial.load_estaciones

# 4. Sitios propios (opcional)
python -m carga_inicial.load_sitios --archivo data/sitios.csv

# 5. Vecinos sitio-estación (opcional)
python -m carga_inicial.match_sitio_estacion --k 5

# 6. Demografía (opcional)
python -m carga_inicial.load_demografia \
  --nivel municipio --archivo data/censo_municipio.csv \
  --anio 2020 --fuente INEGI_CENSO

# 7. Migrar dbo.clima_hist (opcional)
python -m carga_inicial.run_inicial --migrar
```

También puedes usar el runner para varias etapas:

```bash
python -m carga_inicial.run_inicial --init \
  --mg-dir /ruta/mg_2025 --sitios data/sitios.csv
```

---

## 3. Carga de clima 2023 a la fecha

La carga inicial de clima se hace **una sola vez** con el envoltorio de este
bloque, que a su vez usa el loader recurrente. La ventana es **2023-01-01 a la
fecha**; no se carga el histórico anterior.

```bash
# Diarios + mensual oficial + serie mensual propia (2023+)
python -m carga_inicial.backfill_clima

# Solo diarios
python -m carga_inicial.backfill_clima --tipo diario

# Rango concreto dentro de la ventana
python -m carga_inicial.backfill_clima --desde 2023-01-01 --hasta 2025-12-31
```

Si prefieres ejecutar los pasos por separado:

```bash
python -m actualizacion.load_clima_smn --tipo diario --desde 2023-01-01
python -m actualizacion.load_clima_smn --tipo mensual
python -m actualizacion.build_mensual --desde 2023-01 --hasta 2025-12
```

Después de esa carga inicial, el día a día se opera con
`python -m actualizacion.run_diario` y el mes con
`python -m actualizacion.run_mensual`.

### Purgar datos anteriores a 2023

Si ya tienes datos viejos en las tablas `clima_*`, puedes borrarlos una vez:

```bash
python -m carga_inicial.run_inicial --purgar
```

o ejecutar `carga_inicial/sql/06_purgar_antes_2023.sql`. **Es destructivo**:
haz respaldo antes. No borra demografía, porque el Censo 2020 sigue siendo la
edición vigente.

---

## 4. Recargas y cuidado con las llaves foráneas

- `load_inegi --reload` limpia las claves geográficas de estaciones y sitios
  antes de borrar la geografía, y luego hay que volver a ejecutar
  `load_estaciones` y `load_sitios` para reasignarlas.
- Si ya cargaste demografía, `--reload` puede fallar porque
  `demografia_*` referencia municipio/localidad/AGEB. Exporta o limpia esas
  filas antes de recargar y vuelve a cargarlas después.
- `99_drop.sql` elimina **todas** las tablas `*`. Úsalo solo en desarrollo.

---

## 5. Qué tablas deja listas

Todas las tablas se crean en **`DataLake.datos_publicos`**:

- `variable`, `fuente`, `indicador`, `carga_log`.
- `entidad`, `municipio`, `localidad`, `ageb`.
- `estacion`, `sitio`, `sitio_estacion`.
- `clima_diario`, `clima_mensual`, `clima_estatal_mensual`,
  `clima_sitio_mensual`.
- `demografia_municipio`, `demografia_localidad`,
  `demografia_ageb`.

Las vistas de consulta quedan creadas por `03_vistas.sql`.
