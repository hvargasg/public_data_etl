# legacy_dags

DAGs retirados de la operación normal. **Esta carpeta no se monta en
Airflow**: no la agregues al compose ni la pongas dentro de `dags/`.

| Archivo | Estado | Alternativa operativa |
|---|---|---|
| `datos_publicos_estatal_pdf_dag.py` | Legacy / pausado | `datos_publicos_estatal_csv` |

## `datos_publicos_estatal_pdf_dag.py`

Corre `python -m actualizacion.load_estatal_pdf` para cargar la tabla estatal
oficial exacta desde los PDFs del SMN. Se conserva solo como referencia y para
ejecuciones manuales excepcionales.

La fuente operativa es la red reducida en CSV:

```bash
sudo make estatal-csv ARGS="--todo"
```

Diferencias entre CSV y PDFs: ver [`../docs/fuentes.md`](../docs/fuentes.md).

### Ejecución manual

No necesitas Airflow:

```bash
sudo make estatal-pdf ARGS="--desde 2024 --hasta 2026"
sudo make estatal-pdf ARGS="--todo"
```

### Si alguna vez lo necesitas en Airflow

1. Copia el archivo a `dags/`.
2. Verifica que `etl_common` se importe desde `dags/` (el archivo ya usa
   `../dags` cuando vive en `legacy_dags/`; al copiarlo, ajusta esa ruta a
   `.`).
3. Despliega y despausa el DAG.

No agregues `legacy_dags` al montaje de Airflow: se parsearían DAGs que no
deben ejecutarse.
