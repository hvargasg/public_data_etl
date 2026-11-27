"""Carga el Marco Geoestadístico del INEGI en las tablas *.

Soporta dos empaquetados del INEGI:
  * Integrado nacional: 00ent, 00mun, 00l (localidades) y 00a (AGEB).
  * Por entidad: 00ent/01mun/02loc/03ageb (o equivalentes).

Requisitos: geopandas, shapely, pyproj (ver requirements.txt).

Uso:
    python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --version 2025 --reload
    python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --entidades 01,06 --reload
    python -m carga_inicial.load_inegi --mg-dir /ruta/mg_2025 --ageb-shp /ruta/03ageb.shp
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from comun.db import get_engine, insert_rows, log_carga, render_sql
from comun.utils import normalize

SQL_ENT = """
INSERT INTO {{schema}}.entidad (cve_ent, nom_ent, version_mg, geom)
SELECT ?, ?, ?,
       CASE WHEN g.EnvelopeAngle() > 90 THEN g.ReorientObject() ELSE g END
FROM (SELECT geography::STGeomFromText(?, 4326).MakeValid() AS g) x
"""

SQL_MUN = """
INSERT INTO {{schema}}.municipio (cvegeo, cve_ent, cve_mun, nom_mun, version_mg, geom)
SELECT ?, ?, ?, ?, ?,
       CASE WHEN g.EnvelopeAngle() > 90 THEN g.ReorientObject() ELSE g END
FROM (SELECT geography::STGeomFromText(?, 4326).MakeValid() AS g) x
"""

SQL_LOC = """
INSERT INTO {{schema}}.localidad
    (cve_loc, cvegeo, cve_loc_inegi, nom_loc, ambito, version_mg, geom)
SELECT ?, ?, ?, ?, ?, ?,
       CASE WHEN g.EnvelopeAngle() > 90 THEN g.ReorientObject() ELSE g END
FROM (SELECT geography::STGeomFromText(?, 4326).MakeValid() AS g) x
"""

SQL_AGEB = """
INSERT INTO {{schema}}.ageb
    (cve_ageb, cve_loc, cvegeo, cve_ageb_inegi, tipo, version_mg, geom)
SELECT ?, ?, ?, ?, ?, ?,
       CASE WHEN g.EnvelopeAngle() > 90 THEN g.ReorientObject() ELSE g END
FROM (SELECT geography::STGeomFromText(?, 4326).MakeValid() AS g) x
"""

# Nombres de capa del MG integrado y del empaquetado por entidad.
LAYER_ALIASES = {
    "ent": {"00ent", "ent", "entidad", "00entidad"},
    "mun": {"00mun", "mun", "municipio", "01mun"},
    "loc": {"00l", "loc", "localidad", "02loc", "00localidad"},
    "ageb": {"00a", "ageb", "03ageb", "04ageb", "00ageb"},
}


def find_layers(root: Path, token: str, override: str | None = None) -> list[Path]:
    if override:
        path = Path(override)
        if not path.exists():
            raise FileNotFoundError(override)
        return [path]

    aliases = LAYER_ALIASES[token]
    candidates = [
        p for p in root.rglob("*.shp") if normalize(p.stem) in aliases
    ]
    if not candidates:
        candidates = [p for p in root.rglob("*.shp") if token in normalize(p.stem)]
    if not candidates:
        raise FileNotFoundError(f"No encontré la capa '{token}' bajo {root}")

    candidates.sort(
        key=lambda p: (
            "conjuntodedatos" not in normalize(p.parent.name),
            str(p),
        )
    )
    return candidates


def read_layers(root: Path, token: str, override: str | None = None) -> gpd.GeoDataFrame:
    paths = find_layers(root, token, override)
    frames = [gpd.read_file(p) for p in paths]
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def col(gdf: gpd.GeoDataFrame, *names: str) -> str | None:
    for name in names:
        for c in gdf.columns:
            if str(c).lower() == name.lower():
                return c
    for name in names:
        target = normalize(name)
        for c in gdf.columns:
            if normalize(c) == target:
                return c
    return None


def clean_series(raw: gpd.GeoDataFrame, *names: str) -> pd.Series | None:
    column = col(raw, *names)
    if column is None:
        return None
    series = raw[column]
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"nan": "", "None": ""})
        .where(series.notna(), "")
        .fillna("")
    )


def zfill_series(raw: gpd.GeoDataFrame, *names: str, width: int) -> pd.Series | None:
    series = clean_series(raw, *names)
    if series is None:
        return None
    # No convertir un valor vacío en "000...".
    return series.str.zfill(width).where(series != "", "")


def opt_series(raw: gpd.GeoDataFrame, *names: str) -> pd.Series | None:
    column = col(raw, *names)
    return raw[column] if column is not None else None


def clean_text(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    return (
        series.astype(str)
        .str.strip()
        .replace({"nan": None, "None": None, "": None})
        .where(series.notna(), None)
    )


def clean_upper(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": None, "NONE": None, "": None})
        .where(series.notna(), None)
    )


def base_frame(raw: gpd.GeoDataFrame, attrs: dict[str, pd.Series]) -> gpd.GeoDataFrame:
    if raw.crs is None:
        raw = raw.set_crs(4326)
    data = {k: v for k, v in attrs.items() if v is not None}
    data["geometry"] = raw.geometry
    gdf = gpd.GeoDataFrame(data, geometry="geometry", crs=raw.crs).to_crs(4326)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf["geom_wkt"] = gdf.geometry.apply(lambda g: g.wkt)
    return gdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga el Marco Geoestadístico del INEGI.")
    parser.add_argument("--mg-dir", required=True)
    parser.add_argument("--version", default="2025")
    parser.add_argument("--entidades", default="", help="Códigos de entidad separados por coma; vacío = todas.")
    parser.add_argument("--ent-shp", default=None)
    parser.add_argument("--mun-shp", default=None)
    parser.add_argument("--loc-shp", default=None)
    parser.add_argument("--ageb-shp", default=None)
    parser.add_argument("--skip-ageb", action="store_true")
    parser.add_argument("--reload", action="store_true", help="Borra la geografía seleccionada antes de insertar.")
    args = parser.parse_args()

    root = Path(args.mg_dir)
    if not root.exists():
        print(f"No existe {root}", file=sys.stderr)
        return 1

    ents = sorted({e.strip().zfill(2) for e in args.entidades.split(",") if e.strip()})
    engine = get_engine()

    def keep(values: pd.Series) -> pd.Series:
        if not ents:
            return pd.Series([True] * len(values), index=values.index)
        return values.str[:2].isin(ents)

    # ---- Entidades ----
    ent_raw = read_layers(root, "ent", args.ent_shp)
    ent_cve = zfill_series(ent_raw, "CVEGEO", "CVE_ENT", "cve_ent", width=2)
    ent_nom = clean_text(opt_series(ent_raw, "NOMGEO", "NOM_ENT", "nom_ent"))
    ent = base_frame(ent_raw, {"cve_ent": ent_cve, "nom_ent": ent_nom})
    ent = ent[(ent["cve_ent"] != "") & keep(ent["cve_ent"])].drop_duplicates("cve_ent")

    # ---- Municipios ----
    mun_raw = read_layers(root, "mun", args.mun_shp)
    mun_ent = zfill_series(mun_raw, "CVE_ENT", "cve_ent", width=2)
    mun_mun = zfill_series(mun_raw, "CVE_MUN", "cve_mun", width=3)
    mun_cve = zfill_series(mun_raw, "CVEGEO", "cvegeo", width=5)
    if mun_cve is None:
        mun_cve = mun_ent + mun_mun
    mun_nom = clean_text(opt_series(mun_raw, "NOMGEO", "NOM_MUN", "nom_mun"))
    mun = base_frame(
        mun_raw,
        {"cvegeo": mun_cve, "cve_ent": mun_ent, "cve_mun": mun_mun, "nom_mun": mun_nom},
    )
    mun = mun[
        (mun["cvegeo"] != "")
        & (mun["cve_ent"] != "")
        & (mun["cve_mun"] != "")
        & keep(mun["cve_ent"])
    ].drop_duplicates("cvegeo")

    # ---- Localidades ----
    loc_raw = read_layers(root, "loc", args.loc_shp)
    loc_ent = zfill_series(loc_raw, "CVE_ENT", "cve_ent", width=2)
    loc_mun = zfill_series(loc_raw, "CVE_MUN", "cve_mun", width=3)
    loc_loc = zfill_series(loc_raw, "CVE_LOC", "cve_loc", width=4)
    loc_cve = zfill_series(loc_raw, "CVEGEO", "cvegeo", width=9)
    if loc_cve is None:
        loc_cve = loc_ent + loc_mun + loc_loc
    loc_nom = clean_text(opt_series(loc_raw, "NOMGEO", "NOM_LOC", "nom_loc"))
    loc_amb = clean_upper(opt_series(loc_raw, "AMBITO", "ambito"))
    loc = base_frame(
        loc_raw,
        {
            "cve_loc": loc_cve,
            "cvegeo": loc_cve.str[:5],
            "cve_loc_inegi": loc_cve.str[5:9],
            "nom_loc": loc_nom,
            "ambito": loc_amb,
        },
    )
    loc = loc[
        (loc["cve_loc"] != "") & (loc["cvegeo"] != "") & keep(loc["cve_loc"])
    ].drop_duplicates("cve_loc")

    # ---- AGEB (opcional) ----
    ageb = None
    if not args.skip_ageb:
        ageb_raw = read_layers(root, "ageb", args.ageb_shp)
        ageb_ent = zfill_series(ageb_raw, "CVE_ENT", "cve_ent", width=2)
        ageb_mun = zfill_series(ageb_raw, "CVE_MUN", "cve_mun", width=3)
        ageb_loc4 = clean_series(ageb_raw, "CVE_LOC", "cve_loc")
        ageb_ageb = zfill_series(ageb_raw, "CVE_AGEB", "cve_ageb", width=4)
        ageb_cve = clean_series(ageb_raw, "CVEGEO", "cvegeo")
        ageb_amb = clean_upper(opt_series(ageb_raw, "AMBITO", "ambito"))
        ambito = (
            ageb_amb
            if ageb_amb is not None
            else pd.Series([None] * len(ageb_raw), index=ageb_raw.index)
        )

        cvegeo = ageb_ent + ageb_mun
        cve_loc_list: list[str | None] = []
        cve_ageb_list: list[str] = []
        tipo_list: list[str | None] = []

        for i in range(len(ageb_raw)):
            localidad = (ageb_loc4.iloc[i] or "").zfill(4) if ageb_loc4 is not None else ""
            rural = (localidad == "" or localidad == "0000") or str(ambito.iloc[i]).startswith("RURAL")
            clave = (ageb_cve.iloc[i] if ageb_cve is not None else "") or ""
            if rural:
                cve_loc = None
                clave = clave or (cvegeo.iloc[i] + (ageb_ageb.iloc[i] or ""))
            else:
                cve_loc = cvegeo.iloc[i] + localidad
                clave = clave or (cve_loc + (ageb_ageb.iloc[i] or ""))
            cve_loc_list.append(cve_loc)
            cve_ageb_list.append(clave)
            tipo = ambito.iloc[i] if ambito.iloc[i] in {"URBANA", "RURAL"} else None
            tipo_list.append(tipo)

        ageb = base_frame(
            ageb_raw,
            {
                "cve_ageb": pd.Series(cve_ageb_list, index=ageb_raw.index),
                "cve_loc": pd.Series(cve_loc_list, index=ageb_raw.index),
                "cvegeo": cvegeo,
                "cve_ageb_inegi": ageb_ageb,
                "tipo": pd.Series(tipo_list, index=ageb_raw.index),
            },
        )
        ageb = ageb[
            ageb["cve_ageb"].str.len().isin([9, 13]) & keep(ageb["cve_ageb"])
        ].drop_duplicates("cve_ageb")

    # ---- Borrado previo (solo desarrollo / carga inicial) ----
    if args.reload:
        with engine.begin() as conn:
            def where(expr: str) -> tuple[str, tuple]:
                if not ents:
                    return "", ()
                placeholders = ",".join("?" for _ in ents)
                return f" WHERE {expr} IN ({placeholders})", tuple(ents)

            # Las estaciones y sitios referencian la geografía: se limpian sus
            # claves antes de borrar para no violar las llaves foráneas.
            # Después de recargar, vuelve a correr load_estaciones/load_sitios.
            for tabla in ("estacion", "sitio"):
                clause, params = where("cve_ent")
                conn.exec_driver_sql(
                    render_sql(
                        f"UPDATE {{{{schema}}}}.{tabla} "
                        "SET cve_ent = NULL, cvegeo = NULL, cve_loc = NULL, cve_ageb = NULL"
                        + clause
                    ),
                    params,
                )

            if ageb is not None:
                clause, params = where("LEFT(cve_ageb, 2)")
                conn.exec_driver_sql(render_sql("DELETE FROM {{schema}}.ageb" + clause), params)
            clause, params = where("LEFT(cve_loc, 2)")
            conn.exec_driver_sql(render_sql("DELETE FROM {{schema}}.localidad" + clause), params)
            clause, params = where("cve_ent")
            conn.exec_driver_sql(render_sql("DELETE FROM {{schema}}.municipio" + clause), params)
            conn.exec_driver_sql(render_sql("DELETE FROM {{schema}}.entidad" + clause), params)

    # ---- Inserción ----
    with log_carga(engine, "load_inegi", "INEGI_MG") as info:
        info["filas"] += insert_rows(engine, SQL_ENT, [
            (r.cve_ent, r.nom_ent, args.version, r.geom_wkt) for r in ent.itertuples()
        ])
        info["filas"] += insert_rows(engine, SQL_MUN, [
            (r.cvegeo, r.cve_ent, r.cve_mun, r.nom_mun, args.version, r.geom_wkt)
            for r in mun.itertuples()
        ])
        info["filas"] += insert_rows(engine, SQL_LOC, [
            (
                r.cve_loc, r.cvegeo, r.cve_loc_inegi, r.nom_loc, r.ambito,
                args.version, r.geom_wkt,
            )
            for r in loc.itertuples()
        ])
        if ageb is not None:
            info["filas"] += insert_rows(engine, SQL_AGEB, [
                (
                    r.cve_ageb, r.cve_loc, r.cvegeo, r.cve_ageb_inegi, r.tipo,
                    args.version, r.geom_wkt,
                )
                for r in ageb.itertuples()
            ])

    print(
        f"Carga terminada: {len(ent):,} entidades, {len(mun):,} municipios, "
        f"{len(loc):,} localidades"
        + (f", {len(ageb):,} AGEB" if ageb is not None else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
