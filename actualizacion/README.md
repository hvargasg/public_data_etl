# Actualización diaria, mensual y queries

Este bloque contiene **todo lo recurrente**:

- Carga de clima diario del SMN y del SIH.
- Carga de la serie mensual oficial del SMN.
- Construcción de la serie mensual propia (`CALCULADO`).
- Clima mensual derivado para los sitios.
- Claves geográficas (`cvegeo`, `cve_ent`) para las tablas de negocio `dbo`.
- Queries de consulta y control.

No crea estructuras ni carga geografía. Eso está en `carga_inicial/`.

> **Ventana de datos:** 2023-01-01 a la fecha. Los loaders ignoran el
> histórico anterior; si ya tienes datos viejos, usa
> `python -m carga_inicial.run_inicial --purgar`.
>
> Todo opera sobre **`DataLake.datos_publicos`**.

> Los enlaces oficiales de descarga están en
> [`../docs/enlaces.md`](../docs/enlaces.md).

---

## 1. Contenido

```
actualizacion/
├── README.md
├── run_diario.py
├── run_mensual.py
├── run_query.py
├── load_clima_smn.py
├── load_clima_sih.py
├── load_claves_geo.py
├── build_mensual.py
├── sql/
│   └── 10_claves_geo_dbo.sql
└── queries/
    ├── README.md
    ├── 01_vigente.sql
    ├── 02_comparativo_oficial.sql
    ├── 03_cobertura_diaria.sql
    ├── 04_calidad_datos.sql
    └── 05_sitios_clima.sql
```

---

## 2. Flujo diario

```bash
python -m actualizacion.run_diario
```

Hace, en orden:

1. Carga los TXT diarios de los últimos 30 días del SMN.
2. Si pasas `--sih`, carga también los CSV diarios del SIH.
3. Recalcula la serie mensual propia de los meses tocados.

Los pasos son independientes: si el SIH falla, el cálculo mensual sigue y el
script reporta el fallo al final.

Opciones útiles:

```bash
# Últimos 7 días
python -m actualizacion.run_diario --dias 7

# Incluir SIH
python -m actualizacion.run_diario --sih --dias 30

# Rango explícito
python -m actualizacion.run_diario --desde 2025-01-01 --hasta 2025-01-31

# Recalcular estación pero no el clima de sitios
python -m actualizacion.run_diario --dias 7 --sin-sitios
```

Para cargar diarios **sin** recalcular, ejecuta el loader directamente:

```bash
python -m actualizacion.load_clima_smn --tipo diario --dias 7
```

Para un control fino, ejecuta los pasos por separado:

```bash
python -m actualizacion.load_clima_smn --tipo diario --desde 2025-01-01
python -m actualizacion.load_clima_sih --dias 30
python -m actualizacion.build_mensual --desde 2025-01 --hasta 2025-01
```

### Programación diaria (cron)

```cron
0 6 * * * cd /opt/conagua/homologado_db && .venv/bin/python -m actualizacion.run_diario --dias 7 >> logs/diario.log 2>&1
```

---

## 3. Flujo mensual

```bash
python -m actualizacion.run_mensual
```

Hace, en orden:

1. Carga el TXT mensual oficial del SMN para los años indicados
   (por defecto, año actual y anterior; mínimo 2023).
2. Recalcula la serie mensual propia para ese rango.

Opciones útiles:

```bash
# Un año concreto
python -m actualizacion.run_mensual --desde 2025 --hasta 2025

# Recargar todo el rango permitido (2023 a la fecha)
python -m actualizacion.run_mensual --completo

# Solo recalcular lo propio, sin volver a descargar lo oficial
python -m actualizacion.run_mensual --solo-calculo --desde 2025-01 --hasta 2025-12

# Solo cargar lo oficial, sin recalcular
python -m actualizacion.run_mensual --solo-oficial
```

### Programación mensual (cron)

```cron
0 7 3 * * cd /opt/conagua/homologado_db && .venv/bin/python -m actualizacion.run_mensual >> logs/mensual.log 2>&1
```

---

## 4. Claves geográficas de negocio

```bash
python -m actualizacion.load_claves_geo
```

Rellena `cvegeo` (municipio) y `cve_ent` (estado) en `dbo.Clientes` y
`dbo.CEDIS` a partir de sus coordenadas. Usa los polígonos de
`datos_publicos.municipio` y `.entidad`; **no** crea ni recarga geografía.

Reglas:

1. Solo actualiza filas con `cvegeo`/`cve_ent` en `NULL`; nunca sobrescribe.
2. `cve_ent = LEFT(cvegeo, 2)` cuando se resolvió el municipio.
3. Si el punto es válido pero no cae en ningún municipio, usa el polígono de
   entidad para obtener `cve_ent`.
4. Si la coordenada es inválida, usa el texto `Estado` y, si hace falta,
   `Ciudad` (solo `cve_ent`).

El cálculo geométrico corre en SQL Server con los índices espaciales; Python
solo orquesta por lotes para evitar transacciones largas.

Opciones:

```bash
python -m actualizacion.load_claves_geo --tabla clientes
python -m actualizacion.load_claves_geo --tabla cedis
python -m actualizacion.load_claves_geo --limite 2000   # prueba
python -m actualizacion.load_claves_geo --batch 5000    # filas por lote
```

La DDL idempotente de las columnas está en
`actualizacion/sql/10_claves_geo_dbo.sql`. En el servidor se ejecuta con
`make claves-geo` y con el DAG `datos_publicos_claves_geo` (02:00).

---

## 5. Regla calculado vs oficial

- `clima_mensual` guarda filas `CALCULADO / PRELIMINAR` y
  `OFICIAL / DEFINITIVO`.
- `vw_clima_mensual_vigente` prioriza lo oficial y usa lo calculado como
  respaldo.
- `run_mensual` actualiza lo oficial sin borrar lo calculado.
- `build_mensual` borra y recrea solo lo calculado de su rango.

Detalle en `../docs/agregaciones.md`.

---

## 6. Queries de operación

```bash
python -m actualizacion.run_query --archivo actualizacion/queries/01_vigente.sql
python -m actualizacion.run_query --archivo actualizacion/queries/02_comparativo_oficial.sql
python -m actualizacion.run_query --archivo actualizacion/queries/04_calidad_datos.sql
```

También puedes abrirlas en SSMS/Azure Data Studio y editar las variables
`@anio`, `@mes`, `@variable` o `@desde`/`@hasta`.

| Archivo | Para qué sirve |
|---|---|
| `01_vigente.sql` | serie mensual vigente con nombres geográficos |
| `02_comparativo_oficial.sql` | diferencias entre cálculo propio y oficial |
| `03_cobertura_diaria.sql` | días con dato por estación/variable/año |
| `04_calidad_datos.sql` | chequeos de huérfanos, duplicados e incompletos |
| `05_sitios_clima.sql` | clima mensual de sitios (NEAREST vs IDW) |

---

## 7. SIH bloqueado

Si el SIH devuelve HTML o redirecciones 307, descarga los CSV manualmente y
carga desde una carpeta local:

```bash
python -m actualizacion.load_clima_sih --archivo-dir data/sih --dias 30
```

El loader detecta respuestas HTML y las reporta como error en lugar de intentar
parsearlas.

---

## 8. Bitácora

Cada paso escribe en `datos_publicos.carga_log`.

```sql
SELECT TOP (50)
    carga_id, proceso, fuente_id, inicio, fin, filas, estado, mensaje
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
