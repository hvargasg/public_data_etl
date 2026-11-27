"""Utilidades de parseo y geografía para los loaders."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime


def strip_accents(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )


def normalize(value: str) -> str:
    """Minúsculas, sin acentos y solo alfanumérico."""
    value = strip_accents(str(value or "")).lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def decode_text(raw: bytes) -> str:
    """Decodifica UTF-8/Latin-1 y corrige mojibake típico del SIH."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        text = raw.decode("utf-8", errors="replace")

    if "Ã" in text or "Â" in text:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def parse_float(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "" or text.upper() in {"-", "NULO", "NAN", "NULL", "S/D", "SD"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def find_header(lines: list[str], required_any: tuple[str, ...] = ("precipitacion", "tempmax", "temperatura")) -> int | None:
    for i, line in enumerate(lines):
        norm = normalize(line)
        if "fecha" in norm and any(token in norm for token in required_any):
            return i
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
