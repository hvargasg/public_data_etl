# Clima derivado para clientes

Este documento describe el diseño, las decisiones y la operación del clima
asignado a las ubicaciones de `dbo.Clientes` a partir de las estaciones
meteorológicas del SMN.

> **Resumen:** no se crea una tabla diaria cliente × estación. Se usan celdas
> de ~1 km, un puente con las 5 estaciones OPERANDO más cercanas y un hecho
> mensual derivado. El detalle diario se expone como vista, no como tabla.

---

## 1. El problema

`dbo.Clientes` tiene `Lat`/`Lon` por domicilio (83,986 filas, 83,401 con
coordenadas válidas). Se quiere asociar cada cliente con el clima de las
estaciones cercanas sin inflar la base ni duplicar la información de
`clima_diario`.

Las preguntas de diseño eran:

1. ¿Se crea otra tabla con los cruces?
2. ¿Se crea una tabla de clima histórico diario por cliente y estación?

La respuesta es **sí a la primera, no a la segunda**. Abajo se justifica con
mediciones reales del servidor.

---

## 2. Mediciones que sustentan el diseño

### 2.1 Ubicaciones de clientes

| Métrica | Valor |
|---|---:|
| Filas en `dbo.Clientes` | 83,986 |
| Coordenadas válidas (bounding box de México) | 83,401 |
| Puntos únicos exactos | 75,579 |
| Redondeando a ~100 m (3 decimales) | 58,289 |
| **Redondeando a ~1 km (2 decimales)** | **9,451** |
| Redondeando a ~11 km (1 decimal) | 1,080 |

Dato clave: los puntos exactos son casi únicos (75.6k de 83.4k), así que
deduplicar por coordenada exacta ahorra poco. Al redondear a 2 decimales se
colapsa a **9,451 celdas**, una reducción de ~9×.

### 2.2 Distancia a la estación OPERANDO más cercana

| Distancia | Ubicaciones |
|---|---:|
| ≤ 5 km | 43,894 |
| 5–10 km | 17,307 |
| 10–25 km | 13,898 |
| 25–50 km | 3,991 |
| > 50 km | 48 (máx. 68.5 km) |

La gran mayoría está a menos de 10 km de una estación OPERANDO. Con k=5 hay
suficientes vecinas para interpolar incluso donde la más cercana no reporta.

### 2.3 Costo de calcular vecinos

Calcular el vecino más cercano para los ~79k puntos distintos con
`CROSS APPLY TOP 1` tardó **9m15s**. Es aceptable como job periódico, pero no
para responder consultas en vivo. Con 9,451 celdas el mismo cálculo baja a
~1 minuto. Por eso el puente se **persiste** y se refresca por lotes.

### 2.4 Estaciones

| `situacion` | Estaciones | Con datos en los últimos 30 días |
|---|---:|---:|
| `OPERANDO` | 2,786 | 522 |
| `SUSPENDIDA` | 2,740 | 0 |

`OPERANDO` es un estado administrativo, **no** una garantía de que la estación
esté reportando. Por eso el puente se construye con `OPERANDO` (universo
amplio) y el cálculo mensual solo usa las estaciones que tienen valor para ese
mes.

### 2.5 Tamaño de las alternativas

| Grano | Filas por año (por método) |
|---|---:|
| Cliente × variable × día (1 valor derivado) | 83,986 × 365 × 5 ≈ **153 M** |
| Cliente × estación × variable × día (k=3) | ≈ **460 M** |
| Cliente × variable × **mes** | 83,986 × 12 × 5 ≈ **5 M** |
| Celda ~1 km × variable × **mes** | 9,451 × 12 × 5 ≈ **0.57 M** |

Guardar el diario por cliente es entre 250 y 800 veces más grande que el
mensual por celda, y repite el mismo valor de estación para todos los clientes
que la comparten. No se justifica sin un caso de uso concreto. Con ambos
métodos (`NEAREST` + `IDW`) el mensual por celda sigue siendo ~1.13 M
filas/año.

---

## 3. Decisión de arquitectura

```
dbo.Clientes (Lat, Lon, cvegeo, cve_ent)
   │
   └─ cliente_ubicacion_map        (Cliente_id, Direccion_id → ubicacion_id)
        │
        └─ cliente_ubicacion       (celda de ~1 km, geom, cvegeo, cve_ent)
             │
             ├─ cliente_estacion   (k=5 vecinas; distancia, d_altitud, peso IDW)
             │
             └─ clima_cliente_mensual  (variable, año, mes, método, valor)
```

Se reutiliza el patrón que ya existe para `sitio`:

| Sitios | Clientes |
|---|---|
| `sitio` | `cliente_ubicacion` |
| `sitio_estacion` | `cliente_estacion` |
| `clima_sitio_mensual` | `clima_cliente_mensual` |
| `vw_sitio_clima_mensual` | `vw_clima_cliente_mensual` |

La diferencia es que las ubicaciones de clientes se **deduplican por celda**
antes de cruzar, porque hay ~84k domicilios pero solo ~9.5k celdas.

---

## 4. Tablas

Todas viven en `DataLake.datos_publicos` y se crean con
`actualizacion/sql/11_clima_clientes.sql` (idempotente).

### 4.1 `cliente_ubicacion`

Celda de ~1 km que agrupa uno o más domicilios.

| Columna | Tipo | Notas |
|---|---|---|
| `ubicacion_id` | `INT IDENTITY` PK | |
| `lat` | `DECIMAL(9,6)` | `ROUND(Lat, 2)` |
| `lon` | `DECIMAL(9,6)` | `ROUND(Lon, 2)` |
| `geom` | `GEOGRAPHY` | `geography::Point(lat, lon, 4326)` |
| `altitud_m` | `DECIMAL(7,1)` NULL | vacía por ahora (ver §7.4) |
| `cve_ent` | `CHAR(2)` NULL | FK a `entidad` |
| `cvegeo` | `CHAR(5)` NULL | FK a `municipio` |
| `fecha_carga` | `DATETIME2(0)` | UTC |

Restricciones: `UNIQUE (lat, lon)`, checks de rango y coherencia
`LEFT(cvegeo, 2) = cve_ent`.

**Cómo se elige la celda:** `ROUND(CAST(Lat AS DECIMAL(9,6)), 2)` y lo mismo
para `Lon`. Se redondea sobre `DECIMAL` y no sobre `FLOAT` para que el
resultado sea determinista (Lat/Lon en `dbo.Clientes` son `float`). No se usa
el centroide de los clientes de la celda: el punto redondeado es estable,
reproducible y no depende de qué clientes estén en la celda en cada corrida.
El desplazamiento máximo es ~0.005° (~550 m), despreciable frente a las
distancias entre estaciones.

**Geografía:** `cvegeo = MIN(cvegeo)` de los clientes de la celda y
`cve_ent = LEFT(MIN(cvegeo), 2)`, con respaldo en `MIN(cve_ent)` si no hay
municipio. En una celda que cruza un límite estatal se elige el municipio
lexicográficamente menor, de forma determinista. El clima **no** depende de
estas claves; solo sirven para agrupar y reportar.

### 4.2 `cliente_ubicacion_map`

Enlace entre cada domicilio y su celda.

| Columna | Tipo | Notas |
|---|---|---|
| `Cliente_id` | `VARCHAR(255)` PK | mismo tipo que `dbo.Clientes` |
| `Direccion_id` | `SMALLINT` PK | mismo tipo que `dbo.Clientes` |
| `ubicacion_id` | `INT` | FK a `cliente_ubicacion` |
| `fecha_carga` | `DATETIME2(0)` | UTC |

- PK `(Cliente_id, Direccion_id)`. Se verificó que en `dbo.Clientes` no hay
  nulos en `Direccion_id` (0 de 83,986) ni pares duplicados.
- No hay FK a `dbo.Clientes`: la integridad la mantiene el ETL. Esto evita
  acoplar el modelo al esquema `dbo` y permite borrar/recargar clientes sin
  romper la FK.
- Si un domicilio cambia de coordenadas, el `MERGE` actualiza `ubicacion_id`.
- Si un domicilio deja de tener coordenadas válidas, se borra del mapa.
- Índice `ix_cliente_ubicacion_map_ubicacion` para unir por celda.

### 4.3 `cliente_estacion`

Puente con las k estaciones OPERANDO más cercanas a cada celda.

| Columna | Tipo | Notas |
|---|---|---|
| `ubicacion_id` | `INT` PK | FK a `cliente_ubicacion` |
| `estacion_id` | `INT` PK | FK a `estacion` |
| `ranking` | `TINYINT` | 1 = la más cercana (`UNIQUE (ubicacion_id, ranking)`) |
| `distancia_km` | `DECIMAL(6,2)` | distancia geodésica |
| `d_altitud_m` | `DECIMAL(6,1)` NULL | `estacion.altitud_m - cliente_ubicacion.altitud_m` |
| `peso_idw` | `DECIMAL(10,6)` | `1/d²` normalizado por celda |
| `fecha_carga` | `DATETIME2(0)` | UTC |

- Se construye con `situacion = 'OPERANDO'`.
- k por defecto = **5**.
- `peso_idw` se normaliza a suma 1 por celda al construir el puente. En el
  cálculo mensual se vuelve a normalizar sobre las estaciones que sí tienen
  dato (ver §7).
- Índice `ix_cliente_estacion_estacion` para el join por estación.

### 4.4 `clima_cliente_mensual`

Hecho derivado mensual.

| Columna | Tipo | Notas |
|---|---|---|
| `ubicacion_id` | `INT` PK | FK a `cliente_ubicacion` |
| `variable_id` | `TINYINT` PK | FK a `variable` |
| `anio` | `SMALLINT` PK | 2023–2100 |
| `mes` | `TINYINT` PK | 1–12 |
| `metodo` | `VARCHAR(20)` PK | `NEAREST` o `IDW` |
| `valor` | `DECIMAL(10,3)` NULL | |
| `n_estaciones` | `TINYINT` NULL | estaciones que aportaron |
| `fecha_calculo` | `DATETIME2(0)` | UTC |

Índice `ix_clima_cliente_var_periodo` para consultas por variable y periodo.

---

## 5. Vistas

| Vista | Grano | Uso |
|---|---|---|
| `vw_cliente_ubicacion` | celda | nombres de entidad/municipio y nº de domicilios |
| `vw_cliente_estacion` | cliente-domicilio × estación | puente legible |
| `vw_clima_cliente_mensual` | cliente-domicilio × variable × mes × método | consulta principal |
| `vw_clima_diario_vigente` | estación × variable × fecha | diario con prioridad de fuentes |
| `vw_clima_cliente_diario_estacion` | cliente-domicilio × estación × variable × día | auditoría y base del IDW |
| `vw_clima_cliente_diario` | cliente-domicilio × variable × día | IDW diario (a demanda) |
| `vw_clima_cliente_diario_cercano` | cliente-domicilio × variable × día | NEAREST diario |

`vw_clima_cliente_mensual` es la vía recomendada para reportes: ya trae
`variable`, `unidad`, nombres geográficos y `n_estaciones`.

---

## 6. Reglas de cálculo

### 6.1 Ventana temporal

El modelo solo maneja clima desde **2023-01-01**.

| Ejecución | Rango |
|---|---|
| Por defecto (`make clima-clientes`) | últimos **2 meses** (incluye el actual) |
| `--meses N` | últimos N meses |
| `--desde/--hasta` | rango explícito (`YYYY` o `YYYY-MM`) |
| `--todo` | 2023-01 al mes actual |

El DAG diario usa el rango por defecto: recalcula los dos últimos meses, que
es donde llegan datos nuevos y correcciones. Las correcciones oficiales de
meses más viejos se incorporan con una corrida `--todo` o con un rango
explícito.

### 6.2 Fuente de los datos

Se lee `vw_clima_mensual_vigente`, la misma vista que usa el clima de sitios:

- Si existe fila `OFICIAL`, gana la oficial más reciente.
- Si no, se usa la `CALCULADO` propia.

Para el diario, `vw_clima_diario_vigente` aplica la prioridad
`SIH_CSV_DIARIO` > `SMN_TXT_DIARIO` > otras fuentes.

### 6.3 NEAREST

```
valor_celda = valor de la estación con ranking = 1
n_estaciones = 1
```

Si la estación más cercana no tiene dato para ese mes, **no se genera fila**
para ese método. Es el mismo comportamiento que `clima_sitio_mensual`.

### 6.4 IDW

```
peso_i     = 1 / distancia_i²
valor      = Σ(valor_i × peso_i) / Σ(peso_i)
```

Solo entran las estaciones con `valor` no nulo para ese mes. La suma del
denominador se recalcula con las que sí aportaron, así que los pesos se
**renormalizan** automáticamente. `n_estaciones` indica cuántas contribuyeron.

Ventaja: si una de las 5 vecinas deja de reportar, el resultado sigue siendo
válido con las restantes. Desventaja: no corrige altitud ni barreras
orográficas.

### 6.5 Altitud

`cliente_ubicacion.altitud_m` está vacía porque no hay un modelo digital de
elevación en el proyecto. Por eso:

- `d_altitud_m` queda `NULL` y no se aplica gradiente altitudinal.
- La columna existe para no romper el esquema cuando se agregue un DEM.

Para habilitar la corrección en el futuro:

1. Poblar `cliente_ubicacion.altitud_m` desde un DEM.
2. Recalcular `d_altitud_m` en el puente.
3. Aplicar en el IDW una corrección tipo `valor_i + tasa × (altitud_celda − altitud_i)`
   (por ejemplo, −6.5 °C/km para temperatura) antes de ponderar.

Mientras tanto, para temperatura en terreno complejo, el resultado debe
interpretarse como una referencia, no como un valor corregido por altura.

### 6.6 Meses incompletos

Por defecto se incluyen todos los meses, aunque `completo = 0`. Con
`--solo-completos` se excluyen los meses calculados incompletos, pero se
conservan las filas oficiales con `completo = NULL` (el TXT oficial no informa
días con dato). Misma regla que el clima de sitios.

---

## 7. Selección de estaciones

### 7.1 Universo

El puente usa `estacion.situacion = 'OPERANDO'` (2,786 estaciones). No se
congela la lista de "estaciones con datos recientes": eso dejaría fuera
estaciones que reanudan operaciones.

### 7.2 Refresco

- Por defecto, el puente se reconstruye si tiene **más de 30 días**
  (`--dias-puente 30`).
- `--recalcular-puente` fuerza la reconstrucción completa.
- En modo incremental solo se calculan las celdas nuevas.
- El DAG diario aprovecha el refresco automático; no reconstruye todos los días.

### 7.3 Estaciones que dejan de reportar

No hace falta tocar el puente: al calcular el mes, las estaciones sin valor
quedan fuera del IDW y los pesos se renormalizan. NEAREST puede no generar
fila si la más cercana no reportó.

### 7.4 Estaciones que empiezan a reportar

Se incorporan en el siguiente refresco del puente (máximo 30 días), o de
inmediato con `--recalcular-puente`.

### 7.5 Celdas con vecinas lejanas

**16 celdas** (48 puntos de clientes antes de agrupar) tienen su estación
OPERANDO más cercana a más de 50 km (máx. 68.5 km). El dato se calcula igual,
pero debe tratarse como baja confianza. Se puede detectar con
`cliente_estacion.ranking = 1 AND distancia_km > 50`.

---

## 8. Idempotencia e integridad

| Fase | Estrategia |
|---|---|
| DDL | `IF OBJECT_ID(...) IS NULL` y `CREATE OR ALTER VIEW` |
| Celdas | `INSERT ... WHERE NOT EXISTS` + `UPDATE` de geografía faltante |
| Mapa | `DELETE` de domicilios inválidos + `MERGE` por `(Cliente_id, Direccion_id)` |
| Puente | `DELETE` completo cuando toca refrescar, luego `INSERT` |
| Mensual | `DELETE` por método y rango, luego `INSERT` |

Todas las fases se pueden repetir sin duplicar filas. El `DELETE + INSERT` del
mensual es transaccional por método y rango.

Integridad referencial:

- `cliente_ubicacion` → `entidad`, `municipio` (si las claves no son nulas).
- `cliente_estacion` → `cliente_ubicacion`, `estacion`.
- `clima_cliente_mensual` → `cliente_ubicacion`, `variable`.
- `cliente_ubicacion_map` → `cliente_ubicacion`. Hacia `dbo.Clientes` no hay FK:
  la relación la mantiene el ETL.

---

## 9. Operación

### 9.1 Comandos

```bash
# Carga inicial completa (una vez)
sudo make clima-clientes ARGS="--todo --recalcular-puente"

# Rutina diaria: últimos 2 meses; refresca el puente si tiene >30 días
sudo make clima-clientes

# Recalcular un rango
sudo make clima-clientes ARGS="--desde 2025-01 --hasta 2025-12"

# Solo el puente
sudo make clima-clientes ARGS="--sin-mensual"

# Solo el mensual (si el puente ya está)
sudo make clima-clientes ARGS="--sin-puente"

# Prueba del puente con 200 celdas nuevas
sudo make clima-clientes ARGS="--sin-mensual --limite 200"

# Forzar métodos o excluir incompletos
sudo make clima-clientes ARGS="--metodos IDW"
sudo make clima-clientes ARGS="--solo-completos"
```

Equivalente sin `make`:

```bash
python -m actualizacion.build_clima_clientes --todo
```

### 9.2 Salida típica

```
Clima de clientes
  celdas nuevas   : 9,451
  celdas totales  : 9,451
  domicilios      : 83,401
  puente          : 47,255 filas en 9,451 celdas (k=5)
  mensual         : ~4.4 M filas (2023-01..2026-11; NEAREST,IDW)
  filas nuevas    : ~4.4 M
```

Los números exactos dependen de cuántas estaciones tengan dato en cada mes y
de cuántos meses cubra el rango. La cifra de ~4.4 M corresponde a 47 meses ×
9,451 celdas × 5 variables × 2 métodos, sin descontar meses sin dato.

### 9.3 Programación con Airflow

| DAG | Horario (America/Mexico_City) | Comando |
|---|---|---|
| `datos_publicos_claves_geo` | 02:00 | `actualizacion.load_claves_geo` |
| `datos_publicos_clima_clientes` | 03:00 | `actualizacion.build_clima_clientes` |

`claves_geo` corre antes para que las celdas nuevas ya tengan `cvegeo`/`cve_ent`.
El DAG de clima no depende de un Asset; es idempotente y tolera que la
geografía esté incompleta.

Para una carga histórica completa desde Airflow, ejecuta a mano el comando de
la §9.1 (`--todo --recalcular-puente`).

---

## 10. Consultas de verificación

### 10.1 Volumen por tabla

```sql
SELECT
    (SELECT COUNT(*) FROM datos_publicos.cliente_ubicacion)       AS celdas,
    (SELECT COUNT(*) FROM datos_publicos.cliente_ubicacion_map)   AS domicilios,
    (SELECT COUNT(*) FROM datos_publicos.cliente_estacion)        AS puente,
    (SELECT COUNT(*) FROM datos_publicos.clima_cliente_mensual)   AS mensual;
```

### 10.2 Cobertura del puente

```sql
SELECT celdas, COUNT(*) AS celdas_con_puente, MIN(k) AS k_min, MAX(k) AS k_max
FROM (
    SELECT ubicacion_id, COUNT(*) AS k
    FROM datos_publicos.cliente_estacion
    GROUP BY ubicacion_id
) x
CROSS JOIN (SELECT COUNT(*) AS celdas FROM datos_publicos.cliente_ubicacion) y
GROUP BY celdas;
```

### 10.3 Clima de un cliente

```sql
SELECT variable, anio, mes, metodo, valor, n_estaciones
FROM datos_publicos.vw_clima_cliente_mensual
WHERE Cliente_id = '107007417'
  AND Direccion_id = 1
  AND anio = 2025
ORDER BY variable, mes, metodo;
```

### 10.4 Celdas con vecinas lejanas (baja confianza)

```sql
SELECT ce.ubicacion_id, ce.distancia_km, e.clave_smn, e.nombre
FROM datos_publicos.cliente_estacion ce
JOIN datos_publicos.estacion e ON e.estacion_id = ce.estacion_id
WHERE ce.ranking = 1 AND ce.distancia_km > 50
ORDER BY ce.distancia_km DESC;
```

### 10.5 Meses incompletos

```sql
SELECT variable, COUNT(*) AS filas, SUM(CASE WHEN completo = 0 THEN 1 ELSE 0 END) AS incompletos
FROM datos_publicos.vw_clima_cliente_mensual
WHERE metodo = 'IDW'
GROUP BY variable;
```

### 10.6 Clima diario de un cliente (a demanda)

```sql
SELECT variable, fecha, valor, n_estaciones, distancia_media_km
FROM datos_publicos.vw_clima_cliente_diario
WHERE Cliente_id = '107007417'
  AND Direccion_id = 1
  AND fecha BETWEEN '2025-07-01' AND '2025-07-31'
ORDER BY variable, fecha;
```

> **Rendimiento:** las vistas diarias recalculan la prioridad de fuentes sobre
> `clima_diario`. Filtra siempre por `Cliente_id` y un rango corto. Para uso
> intensivo, materializa el rango:

```sql
SELECT *
INTO #clima_diario_cliente
FROM datos_publicos.vw_clima_cliente_diario
WHERE Cliente_id = '107007417'
  AND Direccion_id = 1
  AND fecha BETWEEN '2025-01-01' AND '2025-12-31';
```

---

## 11. Limitaciones

1. **Resolución de ~1 km.** No sirve para microclima intraurbano. Para eso
   haría falta una malla más fina (3 decimales) o un DEM.
2. **Sin corrección altitudinal.** Ver §6.5.
3. **`OPERANDO` no es "reportando".** Solo 522 estaciones tienen datos en los
   últimos 30 días; el IDW lo maneja, pero conviene monitorear `n_estaciones`.
4. **Sin tabla diaria por cliente.** Es una decisión deliberada de tamaño. Si
   aparece un caso de uso, se materializa por rango y variable.
5. **Correcciones oficiales tardías.** El rango por defecto es de 2 meses; un
   cambio oficial de un mes anterior requiere `--todo` o un rango explícito.
6. **Bordes estatales en celdas.** `cvegeo`/`cve_ent` de la celda se eligen de
   forma determinista (`MIN`), pero una celda puede cruzar un límite. El clima
   no depende de esas claves.
7. **Sin FK a `dbo.Clientes`.** La integridad la mantiene el ETL; un borrado
   masivo en `dbo` deja filas en el mapa hasta la siguiente corrida, que las
   elimina.

---

## 12. Registro de decisiones

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| 1 | Puente celda-estación persistido | Calcular vecinos en cada consulta | 9m15s para 79k puntos; inviable en línea |
| 2 | Celdas de ~1 km (2 decimales) | Punto exacto por cliente | 9,451 vs 83,401; el clima no cambia a 1 km |
| 3 | k = 5 | k = 1 o k = 3 | Cubre fallos de estaciones y suaviza el IDW |
| 4 | Solo `situacion = 'OPERANDO'` | Todas las estaciones | Evita usar estaciones suspendidas como vecinas |
| 5 | Filtrar por dato disponible al calcular | Congelar "activas con datos" | Una estación puede reanudar; el IDW se renormaliza |
| 6 | Hecho mensual derivado | Hecho diario por cliente | 0.57 M vs 153 M filas/año |
| 7 | Vistas para el diario | Tabla diaria | No hay caso de uso concreto todavía |
| 8 | IDW 1/d² + NEAREST | Solo NEAREST | NEAREST ignora el gradiente espacial |
| 9 | Leer `vw_clima_mensual_vigente` | Leer `clima_mensual` crudo | Prioriza lo oficial, igual que sitios |
| 10 | Rango por defecto de 2 meses | Todo el histórico en cada corrida | Mantiene fresco lo reciente sin recalcular 47 meses |
| 11 | Refresco del puente cada 30 días | Reconstruir a diario | El puente solo cambia con clientes o estaciones |
| 12 | `altitud_m` nullable, sin corrección | Estimar altitud de la estación | No hay DEM; inventar altitud sesgaría la temperatura |
| 13 | Mapa sin FK a `dbo.Clientes` | FK directa | Desacopla el modelo y permite recargar `dbo` |
| 14 | `cvegeo`/`cve_ent` de la celda con `MIN` | Polígono del centro de celda | Determinista y sin costo; el clima no depende de ello |

---

## 13. Archivos relacionados

| Archivo | Función |
|---|---|
| `actualizacion/sql/11_clima_clientes.sql` | DDL de tablas, índices y vistas |
| `actualizacion/build_clima_clientes.py` | Sincronización, puente y cálculo mensual |
| `dags/datos_publicos_clima_clientes_dag.py` | DAG diario a las 03:00 |
| `Makefile` | Target `clima-clientes` |
| `docs/modelo.md` | Ubicación de las tablas en el modelo estrella |
| `docs/agregaciones.md` | Reglas generales de agregación |
