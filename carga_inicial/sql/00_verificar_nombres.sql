/* ============================================================
   Preflight: detecta tablas existentes en el schema datos_publicos
   con los nombres que usará el modelo. Ejecutar antes de
   `run_inicial --init` si la base DataLake ya tiene objetos.

   Si devuelve filas, revisa si son tablas del propio modelo
   (re-ejecución, es normal) o tablas ajenas (conflicto).
   ============================================================ */

SET NOCOUNT ON;

SELECT t.name AS tabla_existente
FROM sys.tables t
WHERE t.schema_id = SCHEMA_ID('datos_publicos')
  AND t.name IN (
    'variable', 'fuente', 'indicador', 'carga_log',
    'entidad', 'municipio', 'localidad', 'ageb',
    'estacion', 'sitio', 'sitio_estacion',
    'clima_diario', 'clima_mensual', 'clima_estatal_mensual', 'clima_sitio_mensual',
    'demografia_municipio', 'demografia_localidad', 'demografia_ageb'
  )
ORDER BY t.name;
GO
