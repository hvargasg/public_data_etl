# ¿Necesito AGEB?

**Respuesta corta:** para el modelo de clima y para la mayoría de los cruces
demográficos, **no es obligatorio**. La combinación **municipio + localidad** es
el denominador común de casi todas las fuentes públicas. AGEB es una capa
**opcional de detalle urbano** que conviene cargar solo si tus sitios están en
ciudades y necesitas analizar a nivel de colonia o manzana agregada.

> Los enlaces oficiales de INEGI, CONEVAL, CONAPO y AMAI están en
> [`enlaces.md`](enlaces.md).

---

## 1. Qué te da cada nivel

| Nivel | Clave | Cobertura | Fuentes típicas | Cuándo usarlo |
|---|---|---|---|---|
| Entidad | `cve_ent` (2) | 32 | PDFs estatales, series históricas | reportes estatales, comparaciones entre estados |
| Municipio | `cvegeo` (5) | 2,478 | Censo, CONEVAL, CONAPO, DENUE, proyecciones | **nivel base** para casi todo |
| Localidad | `cve_loc` (9) | ~51,700 con polígono | Censo por localidad, algunos CONEVAL/CONAPO | separar urbano/rural, comunidades concretas |
| AGEB | `cve_ageb` (9 o 13) | ~82,000 | Censo 2020 por AGEB, CONEVAL IRS AGEB, CONAPO marginación AGEB, NSE AMAI | detalle intraurbano, riqueza/edad/población por colonia |

### 1.1 Municipio

- Es el nivel con **mayor cobertura y continuidad**.
- Casi todos los indicadores sociales y económicos existen a este nivel.
- Es el nivel natural para series de tiempo largas y para comparar entre
  municipios.
- **Recomendación:** úsalo como llave principal de análisis.

### 1.2 Localidad

- Distingue **urbano vs rural** dentro del municipio.
- El Censo publica población y vivienda por localidad.
- Útil si tus sitios están en comunidades rurales o si necesitas separar la
  cabecera municipal del resto.
- Limitación: muchas localidades rurales pequeñas no tienen todos los
  indicadores, y los polígonos pueden ser puntos o áreas muy pequeñas.

### 1.3 AGEB

- Es la unidad **intraurbana** del INEGI (área geoestadística básica).
- Permite cruzar con:
  - Censo de Población y Vivienda 2020 por AGEB (población, edad, sexo,
    vivienda, hogares, escolaridad).
  - Índice de Rezago Social de CONEVAL por AGEB (ediciones que lo publican).
  - Índice de Marginación de CONAPO por AGEB (ediciones que lo publican).
  - Nivel socioeconómico AMAI por AGEB (**requiere licencia**).
- Es la unidad más fina para **riqueza, edad y población** en ciudades.
- Limitaciones:
  - Solo tiene sentido en zonas urbanas; la AGEB rural existe pero es menos
    útil y no se alinea con la localidad.
  - Los límites cambian entre versiones del Marco Geoestadístico y entre
    censos.
  - No todos los indicadores están publicados a este nivel.
  - Algunos puntos (parques, cuerpos de agua, límites) caen fuera de toda AGEB.

---

## 2. Recomendación para este proyecto

1. **Carga siempre** entidad, municipio y localidad.
2. **Carga AGEB solo si la necesitas.** El modelo ya la tiene como tabla
   opcional (`--skip-ageb` en `carga_inicial.load_inegi`).
3. **No forces** todos los sitios a tener AGEB. `sitio.cve_ageb` es
   nullable y debe quedarse así cuando el punto no cae en una AGEB.
4. **Usa municipio/localidad como llave principal** de las series de clima y de
   la mayoría de los cruces.
5. **Usa AGEB como capa de enriquecimiento**, no como llave primaria de la
   serie temporal. Si necesitas continuidad, agrega AGEB → localidad o
   AGEB → municipio.
6. Si tu análisis de riqueza/edad/población es urbano y necesitas detalle de
   colonia, **sí vale la pena AGEB**; si es municipal o rural, probablemente no.

### 2.1 Regla práctica

| Pregunta | Nivel sugerido |
|---|---|
| ¿Cuánto llovió en el municipio? | municipio |
| ¿Cómo se compara la cabecera con las rancherías? | localidad |
| ¿Qué colonia tiene más población adulta mayor? | AGEB |
| ¿Qué zona urbana tiene mayor rezago social? | AGEB |
| ¿Cómo evoluciona la serie 2023-2025? | municipio o entidad |
| ¿Dónde está mi sitio y qué clima le toca? | sitio + estaciones (no depende de AGEB) |

---

## 3. Cómo se cruza en el modelo

### 3.1 Jerarquía

```
entidad (cve_ent)
  └── municipio (cvegeo)
        └── localidad (cve_loc)
              └── ageb (cve_ageb)   ← opcional
```

- AGEB urbana: `cve_ageb` de 13 caracteres =
  `cve_ent(2) + cve_mun(3) + cve_loc(4) + cve_ageb(4)`.
- AGEB rural: `cve_ageb` de 9 caracteres =
  `cve_ent(2) + cve_mun(3) + cve_ageb(4)`, sin `cve_loc`.
- `ageb.cve_loc` es `NULL` para AGEB rural.

### 3.2 Sitios

`sitio` guarda los cuatro niveles, todos nullable:

```sql
SELECT codigo_sitio, cve_ent, cvegeo, cve_loc, cve_ageb
FROM datos_publicos.sitio;
```

Si `cve_ageb` es `NULL`, el sitio sigue siendo utilizable por municipio o
localidad. No es un error.

### 3.3 Consulta con respaldo por nivel

Para obtener indicadores demográficos del sitio, prioriza AGEB y cae a
localidad o municipio:

```sql
SELECT
    s.codigo_sitio,
    s.cve_ageb,
    s.cve_loc,
    s.cvegeo,
    COALESCE(da.valor, dl.valor, dm.valor) AS poblacion_total
FROM datos_publicos.sitio s
LEFT JOIN datos_publicos.demografia_ageb da
       ON da.cve_ageb = s.cve_ageb
      AND da.anio = 2020
      AND da.indicador_id = (SELECT indicador_id FROM datos_publicos.indicador WHERE codigo = 'POB_TOTAL')
LEFT JOIN datos_publicos.demografia_localidad dl
       ON dl.cve_loc = s.cve_loc
      AND dl.anio = 2020
      AND dl.indicador_id = (SELECT indicador_id FROM datos_publicos.indicador WHERE codigo = 'POB_TOTAL')
LEFT JOIN datos_publicos.demografia_municipio dm
       ON dm.cvegeo = s.cvegeo
      AND dm.anio = 2020
      AND dm.indicador_id = (SELECT indicador_id FROM datos_publicos.indicador WHERE codigo = 'POB_TOTAL');
```

Así no pierdes sitios que no tienen AGEB.

### 3.4 Agregar AGEB a municipio

Si tienes indicadores por AGEB y necesitas una serie municipal comparable:

```sql
SELECT a.cvegeo, d.anio, d.indicador_id, SUM(d.valor) AS valor
FROM datos_publicos.demografia_ageb d
JOIN datos_publicos.ageb a ON a.cve_ageb = d.cve_ageb
GROUP BY a.cvegeo, d.anio, d.indicador_id;
```

Para indicadores que son **promedios** (edad mediana, escolaridad, índices) no
sumes: necesitas el promedio ponderado por población. Guárdalos en el nivel
donde se publican y no los reagregues a ciegas.

---

## 4. Riesgos y cuidados

1. **Cambios de límites**: entre versiones del MG y entre censos, una AGEB puede
   dividirse o fusionarse. Guarda `version_mg` y el año del indicador.
2. **AGEB urbana vs rural**: no mezcles claves de 13 y 9 caracteres en una misma
   llave; el modelo las distingue por longitud.
3. **Puntos fuera de AGEB**: usa `cve_loc` o `cvegeo` como respaldo.
4. **Indicadores no publicados a AGEB**: no inventes una desagregación
   proporcional sin documentarla.
5. **Privacidad**: AGEB es la unidad pública más fina del Censo; si publicas
   resultados, agrega cuando haya pocos registros.
6. **NSE AMAI**: requiere licencia; no viene incluido en este repositorio.

---

## 5. Qué indicadores conviene cargar por nivel

| Indicador | Entidad | Municipio | Localidad | AGEB |
|---|---|---|---|---|
| Población total | ✓ | ✓ | ✓ | ✓ |
| Población por sexo | ✓ | ✓ | ✓ | ✓ |
| Edad mediana | ✓ | ✓ | ✓ | ✓ |
| Grupos de edad | ✓ | ✓ | ✓ | ✓ |
| Viviendas y hogares | ✓ | ✓ | ✓ | ✓ |
| Escolaridad | ✓ | ✓ | — | ✓ |
| PEA | ✓ | ✓ | — | — |
| Rezago social | — | ✓ | ✓ | ✓ |
| Marginación | — | ✓ | ✓ | ✓ |
| NSE AMAI | — | — | — | ✓ (licencia) |
| Proyecciones de población | ✓ | ✓ | — | — |

Las celdas con “—” indican que la fuente no suele publicar ese indicador en ese
nivel, no que sea imposible calcularlo.

---

## 6. Conclusión

- **No necesitas AGEB para arrancar.** Con entidad, municipio y localidad tienes
  un modelo completo y suficiente para clima, demografía básica y reportes.
- **AGEB sí aporta** si tu pregunta es urbana y fina: riqueza, edad y población
  por colonia, rezago social intraurbano, NSE.
- **Diseño elegido:** AGEB opcional, nullable en sitios y estaciones, con
  respaldo explícito a localidad y municipio. Así no bloqueas la operación si no
  cargas AGEB o si un punto no cae en ninguna.
