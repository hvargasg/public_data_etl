SHELL := /usr/bin/env bash

# Opciones de `make deploy`
BRANCH ?= main
REMOTE ?= origin
ALLOW_DIRTY ?= 0

# Si `make deploy` se ejecuta con sudo, git debe correr como el usuario dueño
# del repo (SUDO_USER) para usar sus credenciales SSH.
GIT := $(if $(SUDO_USER),sudo -u $(SUDO_USER) -H git,git)

IMAGE ?= public-data-etl:latest
DOCKER ?= docker
DEPLOY_DOCKER := sudo docker

# Módulo y argumentos para `make etl` / `make etl-infisical`.
MODULO ?= actualizacion.run_diario
ARGS ?= --help

# Query de control para `make query` (nombre dentro de actualizacion/queries/).
QUERY ?= 01_vigente.sql
QUERY_ARGS ?=

# Usa .venv/bin/python si existe.
VENV_PYTHON := $(wildcard .venv/bin/python)
PYTHON ?= $(if $(VENV_PYTHON),$(VENV_PYTHON),python3)

.DEFAULT_GOAL := help

.PHONY: help env check build diario mensual inicial backfill claves-geo clima-clientes estatal-csv estatal-pdf query etl etl-infisical check-infisical shell clean deploy

help: ## Muestra esta ayuda
	@awk 'BEGIN {FS = ":.*## "; printf "Uso: make <objetivo>\n\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Crea .env a partir de .env.example (no sobrescribe)
	@if [ -f .env ]; then \
		echo ".env ya existe; no se modifica."; \
	else \
		cp .env.example .env && chmod 600 .env; \
		echo "Creado .env (modo 600). Completa las credenciales."; \
	fi

check: ## Compila el código y revisa las CLI (usa la imagen si existe)
	@set -e; \
	MODULOS="carga_inicial.run_inicial carga_inicial.backfill_clima \
		actualizacion.run_diario actualizacion.run_mensual actualizacion.run_query \
		actualizacion.load_claves_geo actualizacion.build_clima_clientes \
		actualizacion.load_estatal_csv actualizacion.load_estatal_pdf"; \
	if $(DOCKER) image inspect $(IMAGE) >/dev/null 2>&1; then \
		echo "check: usando la imagen $(IMAGE)"; \
		$(DOCKER) run --rm --entrypoint bash $(IMAGE) -c \
			"python -m compileall -q comun carga_inicial actualizacion && \
			 for m in $$MODULOS; do python -m \$$m --help >/dev/null; done"; \
		$(PYTHON) -m compileall -q dags; \
	else \
		echo "check: usando Python local ($(PYTHON))"; \
		$(PYTHON) -m compileall -q comun carga_inicial actualizacion dags; \
		for m in $$MODULOS; do $(PYTHON) -m $$m --help >/dev/null; done; \
	fi; \
	echo "check OK"

build: ## Construye la imagen del ETL
	@$(DOCKER) build -t $(IMAGE) .

diario: ## Actualización diaria con .env o Infisical (ARGS="--dias 7")
	@ETL_MODULO=actualizacion.run_diario ./scripts/etl-infisical.sh $(ARGS)

mensual: ## Actualización mensual (ARGS="--completo")
	@ETL_MODULO=actualizacion.run_mensual ./scripts/etl-infisical.sh $(ARGS)

inicial: ## Carga inicial/ocasional (ARGS="--init")
	@ETL_MODULO=carga_inicial.run_inicial ./scripts/etl-infisical.sh $(ARGS)

backfill: ## Carga histórica de clima 2023+ (ARGS="--tipo diario")
	@ETL_MODULO=carga_inicial.backfill_clima ./scripts/etl-infisical.sh $(ARGS)

claves-geo: ## Asigna cvegeo/cve_ent en dbo.Clientes y dbo.CEDIS (ARGS="--tabla ambas")
	@ETL_MODULO=actualizacion.load_claves_geo ./scripts/etl-infisical.sh $(ARGS)

clima-clientes: ## Deriva clima mensual de clientes desde estaciones vecinas (ARGS="--todo")
	@ETL_MODULO=actualizacion.build_clima_clientes ./scripts/etl-infisical.sh $(ARGS)

estatal-csv: ## Carga la serie estatal desde la red reducida SMN en CSV (ARGS="--todo")
	@ETL_MODULO=actualizacion.load_estatal_csv ./scripts/etl-infisical.sh $(ARGS)

estatal-pdf: ## LEGACY: PDFs estatales del SMN (ARGS="--todo"); DAG en legacy_dags/
	@ETL_MODULO=actualizacion.load_estatal_pdf ./scripts/etl-infisical.sh $(ARGS)

query: ## Ejecuta una query de control (QUERY=04_calidad_datos.sql QUERY_ARGS="--limite 50")
	@ETL_MODULO=actualizacion.run_query ./scripts/etl-infisical.sh \
		--archivo /app/actualizacion/queries/$(QUERY) $(QUERY_ARGS)

etl: ## Ejecuta un módulo con .env o Infisical (MODULO=... ARGS="...")
	@ETL_MODULO=$(MODULO) ./scripts/etl-infisical.sh $(ARGS)

etl-infisical: ## Fuerza el uso de Infisical (servidor)
	@SECRETS_SOURCE=infisical ETL_MODULO=$(MODULO) ./scripts/etl-infisical.sh $(ARGS)

check-infisical: ## Valida login y secretos de Infisical sin tocar la base
	@SECRETS_SOURCE=infisical ./scripts/etl-infisical.sh --help >/dev/null && echo "infisical OK"

shell: ## Abre una shell en el contenedor del ETL
	@$(DOCKER) run --rm -it \
		--user "$${ETL_UID:-1000:1000}" \
		--workdir /app \
		--mount "type=bind,source=$${ETL_DATA:-$(CURDIR)/data},target=/app/data" \
		--entrypoint bash $(IMAGE)

clean: ## Borra las cachés locales de Python
	@find comun carga_inicial actualizacion dags -name __pycache__ -type d -prune -exec rm -rf {} +

deploy: ## Pull, reconstruye la imagen si cambió y valida el ETL (servidor)
	@set -euo pipefail; \
	cd "$(CURDIR)"; \
	if [ "$(ALLOW_DIRTY)" != "1" ] && [ -n "$$($(GIT) status --porcelain)" ]; then \
		echo "ERROR: hay cambios locales sin commitear. Revisa 'git status' o usa ALLOW_DIRTY=1." >&2; \
		exit 1; \
	fi; \
	BEFORE="$$($(GIT) rev-parse HEAD)"; \
	echo "==> git pull --ff-only $(REMOTE) $(BRANCH)"; \
	$(GIT) pull --ff-only "$(REMOTE)" "$(BRANCH)"; \
	AFTER="$$($(GIT) rev-parse HEAD)"; \
	CHANGED="$$($(GIT) diff --name-only "$$BEFORE" "$$AFTER")"; \
	if [ "$$BEFORE" = "$$AFTER" ]; then \
		echo "==> sin cambios de código"; \
	else \
		echo "==> archivos cambiados:"; \
		printf '%s\n' "$$CHANGED"; \
	fi; \
	STATE_FILE="/var/lib/public-data-etl-deploy/build-fingerprint"; \
	DOCKER_ARCH="$$($(DEPLOY_DOCKER) info --format '{{.Architecture}}')"; \
	FILE_HASHES="$$(find Dockerfile .dockerignore comun carga_inicial actualizacion requirements.txt \
		-path '*/__pycache__' -prune -o -type f -print0 \
		| sort -z | xargs -0 sha256sum)"; \
	FINGERPRINT="$$(printf '%s\n%s\n' "$$FILE_HASHES" "$$DOCKER_ARCH" | sha256sum | awk '{print $$1}')"; \
	STORED_FINGERPRINT="$$(sudo cat "$$STATE_FILE" 2>/dev/null || true)"; \
	IMAGE_ID="$$( $(DEPLOY_DOCKER) image inspect "$(IMAGE)" --format '{{.Id}}' 2>/dev/null || true )"; \
	BUILD=0; \
	if [ -z "$$IMAGE_ID" ] || [ "$$FINGERPRINT" != "$$STORED_FINGERPRINT" ]; then \
		BUILD=1; \
	fi; \
	if [ "$$BUILD" = "1" ]; then \
		echo "==> huella de build diferente o imagen inexistente"; \
		echo "==> construyendo $(IMAGE)"; \
		$(DEPLOY_DOCKER) build -t "$(IMAGE)" .; \
	else \
		echo "==> imagen $(IMAGE) sin cambios; se omite el build"; \
	fi; \
	echo "==> validando la CLI dentro de la imagen"; \
	$(DEPLOY_DOCKER) run --rm --entrypoint python "$(IMAGE)" -m actualizacion.run_diario --help >/dev/null; \
	if [ "$$BUILD" = "1" ]; then \
		sudo install -d -m 755 /var/lib/public-data-etl-deploy; \
		printf '%s\n' "$$FINGERPRINT" | sudo tee "$$STATE_FILE" >/dev/null; \
		echo "==> huella de build guardada"; \
	fi; \
	echo "==> estado final"; \
	$(GIT) log -1 --oneline; \
	$(DEPLOY_DOCKER) image inspect "$(IMAGE)" --format 'imagen: {{.Id}}'; \
	if printf '%s\n' "$$CHANGED" | grep -q '^dags/'; then \
		echo "==> DAGs actualizados: Airflow los recargará desde el directorio montado"; \
	fi
