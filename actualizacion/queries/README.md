# Queries de operación

Consultas listas para revisar la serie mensual, comparar calculado vs oficial,
medir cobertura y detectar problemas de calidad.

> La ventana vigente del modelo es **2023-01-01 a la fecha**; las queries usan
> ese rango por defecto.
>
> Las queries usan el token `{{schema}}`. `python -m actualizacion.run_query`
> lo reemplaza por `DB_SCHEMA` (`datos_publicos`). Si las abres en SSMS,
> reemplaza el token por `datos_publicos`.

## Cómo ejecutarlas

Desde `homologado_db/`:

```bash
python -m actualizacion.run_query --archivo actualizacion/queries/01_vigente.sql
python -m actualizacion.run_query --archivo actualizacion/queries/04_calidad_datos.sql
```

O ábrelas en SSMS / Azure Data Studio y ejecuta el bloque completo. Cada archivo
trae variables al inicio (`@anio`, `@mes`, `@variable`, `@desde`, `@hasta`) que
puedes editar.

## Catálogo

| Archivo | Devuelve |
|---|---|
| `01_vigente.sql` | serie mensual vigente (oficial si existe, si no calculada) con entidad, municipio, localidad y estación |
| `02_comparativo_oficial.sql` | diferencias entre la fila `CALCULADO` y la `OFICIAL` del mismo periodo |
| `03_cobertura_diaria.sql` | días con dato por estación, variable y año |
| `04_calidad_datos.sql` | una tabla de chequeos: estaciones sin municipio, sitios sin localidad, meses incompletos, duplicados en la vista vigente, etc. |
| `05_sitios_clima.sql` | clima mensual de cada sitio por `NEAREST` e `IDW` |

## Interpretación rápida de `04_calidad_datos.sql`

- `estaciones_sin_municipio`: suele indicar que falta cargar geografía o que el
  punto cae fuera del país.
- `sitios_sin_localidad`: normal en puntos rurales o aislados; no bloquea.
- `meses_calculados_incompletos`: meses con menos días de los esperados. Revisa
  `dias_con_dato` antes de usar `PREC` como total mensual.
- `duplicados_en_vista_vigente`: debe ser **0**. Si no, hay un problema en la
  lógica de prioridad o una carga incompleta.
- `estaciones_sin_datos_diarios`: estaciones del catálogo que nunca se han
  cargado.
- `oficial_sin_calculado`: meses con dato oficial pero sin respaldo propio;
  útil para saber dónde no tienes serie diaria.
