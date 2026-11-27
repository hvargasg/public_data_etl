/* ============================================================
   Elimina TODAS las estructuras del modelo homologado.
   Uso: solo en desarrollo o reinstalación controlada.
   ============================================================ */

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

DROP VIEW IF EXISTS {{schema}}.vw_clima_hist_compat;
DROP VIEW IF EXISTS {{schema}}.vw_sitio_clima_cercano;
DROP VIEW IF EXISTS {{schema}}.vw_sitio_clima_mensual;
DROP VIEW IF EXISTS {{schema}}.vw_sitio_geografia;
DROP VIEW IF EXISTS {{schema}}.vw_clima_mensual_geo;
DROP VIEW IF EXISTS {{schema}}.vw_clima_mensual_vigente;
GO

DROP TABLE IF EXISTS {{schema}}.demografia_ageb;
DROP TABLE IF EXISTS {{schema}}.demografia_localidad;
DROP TABLE IF EXISTS {{schema}}.demografia_municipio;
DROP TABLE IF EXISTS {{schema}}.clima_sitio_mensual;
DROP TABLE IF EXISTS {{schema}}.clima_estatal_mensual;
DROP TABLE IF EXISTS {{schema}}.clima_mensual;
DROP TABLE IF EXISTS {{schema}}.clima_diario;
DROP TABLE IF EXISTS {{schema}}.sitio_estacion;
DROP TABLE IF EXISTS {{schema}}.sitio;
DROP TABLE IF EXISTS {{schema}}.estacion;
DROP TABLE IF EXISTS {{schema}}.ageb;
DROP TABLE IF EXISTS {{schema}}.localidad;
DROP TABLE IF EXISTS {{schema}}.municipio;
DROP TABLE IF EXISTS {{schema}}.entidad;
DROP TABLE IF EXISTS {{schema}}.carga_log;
DROP TABLE IF EXISTS {{schema}}.indicador;
DROP TABLE IF EXISTS {{schema}}.fuente;
DROP TABLE IF EXISTS {{schema}}.variable;
GO
