FROM python:3.12-slim-bookworm

ARG MSODBC_VERSION=18

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Driver ODBC para SQL Server
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      gnupg \
      ca-certificates \
      unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
      -o /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
      msodbcsql${MSODBC_VERSION} \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONPATH=/app \
    ETL_DATA_DIR=/app/data

# Dependencias
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir -r requirements.txt

# Código del ETL (carga inicial y actualización recurrente)
COPY comun ./comun
COPY carga_inicial ./carga_inicial
COPY actualizacion ./actualizacion

# `data/` se monta en tiempo de ejecución en /app/data.
ENTRYPOINT ["python"]
CMD ["-m", "actualizacion.run_diario", "--help"]
