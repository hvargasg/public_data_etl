# Agregaciones y reglas de cálculo

Este documento explica cómo se pasa de lo diario a lo mensual, cómo se elige
entre fuentes y cómo se marca la calidad del dato.

> **Ventana de cálculo:** el modelo solo agrega datos desde **2023-01-01** a la
> fecha. El histórico anterior no se carga ni se recalcula.

---

## 1. Regla por variable

La regla vive en `datos_publicos.variable.agregacion`:

| Variable | Unidad | Agregación diaria → mensual |
|---|---|---|
| `PREC` | mm | **SUMA** de los días con dato |
| `EVAP` | mm | **SUMA** de los días con dato |
| `TMAX` | °C | **MEDIA** de los días con dato |
| `TMED` | °C | **MEDIA** de los días con dato |
| `TMIN` | °C | **MEDIA** de los días con dato |

No se rellenan días faltantes con cero ni con interpolación. Un día sin dato no
entra en la suma ni en el promedio; solo afecta la bandera de completitud.

> **Precaución con `PREC`:** la suma de días con dato **no** es una estimación
> del total mensual si faltan días. Por eso se guarda `dias_con_dato` y
> `completo`. Para reportes que necesiten el total mensual, decide explícitamente
> si aceptas meses incompletos o si aplicas una expansión (por ejemplo,
> `valor * dias_esperados / dias_con_dato`) y documenta esa decisión.

---

## 2. Prioridad de fuentes diarias

Si una estación tiene el mismo `(variable, fecha)` en más de una fuente:

1. `SIH_CSV_DIARIO` (prioridad 0).
2. `SMN_TXT_DIARIO` (prioridad 1).
3. Cualquier otra fuente (prioridad 9).

La elección se hace con `ROW_NUMBER()` por
`(estacion_id, variable_id, fecha)` ordenado por prioridad. Solo se usa la fila
de mayor prioridad; las demás quedan en `clima_diario` para auditoría pero
no entran al cálculo.

Esto permite corregir un día con el SIH sin borrar el dato del SMN.

---

## 3. Cálculo mensual propio

`actualizacion/build_mensual.py` ejecuta, por cada estación y variable:

```
para cada (anio, mes):
    dias_con_dato  = COUNT(valor no nulo)
    dias_esperados = días del mes (28..31)
    valor          = SUM(valor)   si agregacion = 'SUMA'
                   = AVG(valor)   si agregacion = 'MEDIA'
    fecha_corte    = MAX(fecha)
    completo       = dias_con_dato >= dias_esperados
```

Se inserta en `clima_mensual` con:

- `origen = 'CALCULADO'`
- `estado = 'PRELIMINAR'`
- `fuente_id = CALCULO_PROPIO`

Antes de insertar, se borran las filas `CALCULADO` de `CALCULO_PROPIO` en el
rango solicitado. Las filas `OFICIAL` **nunca** se borran.

### 3.1 Pseudocódigo SQL

La consulta real está en `actualizacion/build_mensual.py` (`SQL_BUILD_MENSUAL`). Su forma
es:

```sql
WITH ranked AS (
    SELECT d.*,
           ROW_NUMBER() OVER (
               PARTITION BY d.estacion_id, d.variable_id, d.fecha
               ORDER BY CASE d.fuente_id
                            WHEN @sih THEN 0
                            WHEN @smn THEN 1
                            ELSE 9
                        END
           ) AS rn
    FROM datos_publicos.clima_diario d
    WHERE d.valor IS NOT NULL
      AND d.fecha BETWEEN @desde AND @hasta
),
base AS (
    SELECT * FROM ranked WHERE rn = 1
),
agg AS (
    SELECT b.estacion_id, b.variable_id,
           YEAR(b.fecha)  AS anio,
           MONTH(b.fecha) AS mes,
           CASE WHEN v.agregacion = 'SUMA'
                THEN SUM(b.valor) ELSE AVG(b.valor) END AS valor,
           COUNT(*)      AS dias_con_dato,
           MAX(b.fecha)  AS fecha_corte
    FROM base b
    JOIN datos_publicos.variable v ON v.variable_id = b.variable_id
    GROUP BY b.estacion_id, b.variable_id,
             YEAR(b.fecha), MONTH(b.fecha), v.agregacion
)
INSERT INTO datos_publicos.clima_mensual (...)
SELECT ..., 'CALCULADO', 'PRELIMINAR', @calculo,
       dias_con_dato,
       DAY(EOMONTH(DATEFROMPARTS(anio, mes, 1))),
       CASE WHEN dias_con_dato >= DAY(EOMONTH(DATEFROMPARTS(anio, mes, 1)))
            THEN 1 ELSE 0 END,
       fecha_corte
FROM agg;
```

---

## 4. Cálculo mensual oficial

`actualizacion/load_clima_smn.py --tipo mensual` lee el TXT oficial y guarda:

- `origen = 'OFICIAL'`
- `estado = 'DEFINITIVO'`
- `fuente_id = SMN_TXT_MENSUAL`
- `dias_con_dato = NULL` y `completo = NULL`: el TXT mensual no informa días
  con dato (la columna `MESES` cuenta meses del año, no días).
- `dias_esperados` = días del mes
- `fecha_corte` = fecha de emisión del archivo

También se puede cargar el SIH como fuente diaria y recalcular lo mensual; en
ese caso el resultado sigue siendo `CALCULADO`, no `OFICIAL`.

---

## 5. Coexistencia y vista vigente

Para un mismo `(estacion_id, variable_id, anio, mes)` pueden existir:

| origen | estado | fuente | cuándo |
|---|---|---|---|
| `CALCULADO` | `PRELIMINAR` | `CALCULO_PROPIO` | siempre que haya diarios |
| `OFICIAL` | `DEFINITIVO` | `SMN_TXT_MENSUAL` | cuando el SMN publica |

`datos_publicos.vw_clima_mensual_vigente` devuelve **una sola fila**:

```sql
ROW_NUMBER() OVER (
    PARTITION BY estacion_id, variable_id, anio, mes
    ORDER BY CASE WHEN origen = 'OFICIAL' THEN 0 ELSE 1 END,
             fecha_carga DESC
)
```

- Si hay oficial, gana la oficial más reciente.
- Si no hay oficial, se usa la calculada.
- La calculada sigue existiendo en la tabla para auditoría y para comparar.

Consulta típica:

```sql
SELECT *
FROM datos_publicos.vw_clima_mensual_geo
WHERE variable = 'PREC'
  AND anio = 2025
ORDER BY nom_ent, nom_mun, estacion_nombre, mes;
```

Para ver el respaldo propio cuando ya hay oficial:

```sql
SELECT origen, estado, valor, dias_con_dato, dias_esperados, completo, fecha_corte
FROM datos_publicos.clima_mensual
WHERE estacion_id = 123
  AND variable_id = 1
  AND anio = 2025 AND mes = 7;
```

---

## 6. Comparación calculado vs oficial

Para detectar diferencias sistemáticas:

```sql
SELECT
    c.estacion_id,
    c.variable_id,
    c.anio,
    c.mes,
    c.valor  AS calculado,
    o.valor  AS oficial,
    c.valor - o.valor AS diferencia,
    c.dias_con_dato,
    c.dias_esperados,
    c.completo
FROM datos_publicos.clima_mensual c
JOIN datos_publicos.clima_mensual o
  ON o.estacion_id = c.estacion_id
 AND o.variable_id = c.variable_id
 AND o.anio = c.anio
 AND o.mes = c.mes
WHERE c.origen = 'CALCULADO'
  AND o.origen = 'OFICIAL'
  AND c.anio = 2025;
```

Guarda esta comparación como control de calidad mensual.

---

## 7. Clima mensual por sitio

`actualizacion/build_mensual.py` puede derivar `clima_sitio_mensual` con dos métodos:

### 7.1 NEAREST

Usa la estación con `ranking = 1` en `sitio_estacion`:

```
valor_sitio = valor_estacion_mas_cercana
n_estaciones = 1
```

Ventaja: simple y reproducible. Desventaja: ignora el gradiente espacial.

### 7.2 IDW

Promedio ponderado por el inverso de la distancia al cuadrado:

```
peso_i = 1 / distancia_i^2        (normalizado a suma 1)
valor_sitio = Σ (valor_i * peso_i) / Σ peso_i
```

Solo se usan estaciones con valor no nulo para ese mes. `n_estaciones` indica
cuántas contribuyeron.

Ventaja: suaviza el ruido local. Desventaja: no corrige altitud ni barreras
orográficas; para series de temperatura en terreno complejo, considera un
modelo con gradiente altitudinal.

### 7.3 Fuente de entrada

Ambos métodos leen `vw_clima_mensual_vigente`, es decir, usan lo oficial
cuando existe y lo calculado cuando no. Así el clima de sitios se actualiza
solo cuando llega lo oficial.

### 7.4 Meses incompletos

Por defecto se incluyen todos los meses, aunque `completo = 0`. Usa
`--solo-completos` si prefieres excluir meses con días faltantes. Las filas
oficiales con `completo = NULL` (porque el TXT mensual no informa días) se
conservan: no se descarta lo oficial por falta de metadato de completitud.

---

## 8. Serie estatal

`clima_estatal_mensual` guarda la serie de entidad-mes:

- De los PDFs de CONAGUA (`PDF_ESTATAL`).
- De la migración de `dbo.clima_hist` (`PDF_ESTATAL`).
- Opcionalmente, de la red reducida (`SMN_RED_CSV`).

Esta tabla **no** se calcula desde estaciones; es una serie independiente para
reportes estatales y compatibilidad.

---

## 9. Casos borde

| Caso | Tratamiento |
|---|---|
| Día con `NULO` o celda vacía | no se inserta; no entra a la suma/media |
| Valor `0` | es un dato válido; sí entra |
| Mes sin ningún día | no se genera fila mensual calculada |
| Febrero bisiesto | `dias_esperados = 29` |
| Estación con dos fuentes el mismo día | gana la de mayor prioridad |
| Recarga del mismo rango | borra e inserta; no duplica |
| Año o mes fuera de rango | rechazado por `CHECK` |
| Valor negativo en `PREC`/`EVAP` | se acepta tal cual; revisa `flag_calidad` si detectas anomalías |
| AGEB rural | clave de 9 caracteres; no se le asigna `cve_loc` |

---

## 10. Consultas de validación

### 10.1 Cobertura diaria por estación y año

```sql
SELECT estacion_id, variable_id, YEAR(fecha) AS anio, COUNT(*) AS dias
FROM datos_publicos.clima_diario
GROUP BY estacion_id, variable_id, YEAR(fecha)
ORDER BY anio DESC, dias ASC;
```

### 10.2 Meses calculados incompletos

```sql
SELECT estacion_id, variable_id, anio, mes,
       dias_con_dato, dias_esperados,
       dias_esperados - dias_con_dato AS faltantes
FROM datos_publicos.clima_mensual
WHERE origen = 'CALCULADO'
  AND completo = 0
ORDER BY anio DESC, mes DESC, faltantes DESC;
```

### 10.3 Duplicados en el mensual vigente

```sql
SELECT estacion_id, variable_id, anio, mes, COUNT(*) AS filas
FROM datos_publicos.vw_clima_mensual_vigente
GROUP BY estacion_id, variable_id, anio, mes
HAVING COUNT(*) > 1;
```

Debe devolver cero filas.

### 10.4 Sitios sin clima derivado

```sql
SELECT s.sitio_id, s.codigo_sitio
FROM datos_publicos.sitio s
WHERE NOT EXISTS (
    SELECT 1 FROM datos_publicos.clima_sitio_mensual c
    WHERE c.sitio_id = s.sitio_id
);
```

---

## 11. Reproducibilidad

- La agregación depende solo de `clima_diario`, la prioridad de fuentes y
  `variable.agregacion`.
- Si cambia una fuente, vuelve a correr `build_mensual` para el rango afectado.
- `fecha_corte` y `fecha_carga` permiten saber con qué versión se calculó.
- No hay aleatoriedad ni imputación implícita.
