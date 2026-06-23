SHELL := /bin/bash

COMPOSE ?= docker compose
COMPOSE_ENV_FILE ?= .env.compose
COMPOSE_FILES ?= docker-compose.yml
APP_ENV_FILE ?= .env
APP_SERVICE ?= app
DB_SERVICE ?= db
IMAGE ?= ghcr.io/14zy/worldkycproject:latest
COMPOSE_FILE_ARGS := $(foreach file,$(COMPOSE_FILES),-f $(file))

PYTHON_FILES := main.py \
	api/worldKycApi.py \
	controller/authController.py \
	controller/customerSearchHandler.py \
	controller/tmaController.py \
	data/repository/userRepository.py \
	handler/message_handler.py \
	handler/inline_handler.py \
	utils/telegram_mini_app.py

FRONTEND_DIR := frontend

.PHONY: help setup run dev check clean compose-config pull deploy up down restart ps logs build migrate revision

help:
	@printf "%-16s %s\n" "help" "Show available commands"
	@printf "%-16s %s\n" "setup" "Install frontend dependencies"
	@printf "%-16s %s\n" "run" "Run the app locally; use env_file=.env to override"
	@printf "%-16s %s\n" "dev" "Run the frontend development server"
	@printf "%-16s %s\n" "check" "Build the frontend and compile Python files"
	@printf "%-16s %s\n" "clean" "Remove Python cache directories and files"
	@printf "%-16s %s\n" "build" "Build the local Docker image $(IMAGE)"
	@printf "%-16s %s\n" "migrate" "Run Alembic migrations against the configured database"
	@printf "%-16s %s\n" "revision" "Create a new Alembic migration; use msg='description'"
	@printf "%-16s %s\n" "up" "Start compose services; use service=db and/or build=local"
	@printf "%-16s %s\n" "down" "Stop the compose stack"
	@printf "%-16s %s\n" "restart" "Restart compose services; use service=db"
	@printf "%-16s %s\n" "ps" "Show compose status; use service=db"
	@printf "%-16s %s\n" "logs" "Follow logs; default app, use service=db or service=all"
	@printf "%-16s %s\n" "" ""
	@printf "%-16s %s\n" "Project Helpers" ""
	@printf "%-16s %s\n" "compose-config" "Validate docker compose configuration"
	@printf "%-16s %s\n" "pull" "Pull compose images"
	@printf "%-16s %s\n" "deploy" "Run git pull, pull compose images, and start services"
	@printf "%-16s %s\n" "" "Set compose_files='docker-compose.yml docker-compose.mailcow.yml' to include mailcow network"

run:
	@test -f "$(if $(env_file),$(env_file),$(APP_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(APP_ENV_FILE)) file not found"; exit 1; }
	python3 main.py

migrate:
	@test -f "$(if $(env_file),$(env_file),$(APP_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(APP_ENV_FILE)) file not found"; exit 1; }
	alembic upgrade head

revision:
	@test -n "$(msg)" || { echo "Use msg='description'"; exit 1; }
	alembic revision -m "$(msg)"

setup:
	npm install --prefix "$(FRONTEND_DIR)"

dev:
	npm run dev --prefix "$(FRONTEND_DIR)"

check: setup
	npm run build --prefix "$(FRONTEND_DIR)"
	python3 -m py_compile $(PYTHON_FILES)

clean:
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

compose-config:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" config

pull:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" pull

deploy:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	git pull
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" pull
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" up -d

up:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	@if [ -n "$(build)" ] && [ "$(build)" != "local" ]; then \
		echo "Unsupported build '$(build)'. Use build=local."; \
		exit 1; \
	fi
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" up -d $(if $(filter local,$(build)),--build,) $(if $(filter all,$(service)),,$(if $(service),$(service),))

down:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" down

restart:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	@if [ -n "$(service)" ] && [ "$(service)" != "all" ]; then \
		$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" restart "$(service)"; \
	else \
		$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" down; \
		$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" up -d; \
	fi

ps:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" ps $(if $(filter all,$(service)),,$(if $(service),$(service),))

logs:
	@test -f "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" || { echo "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE)) file not found"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILE_ARGS) --env-file "$(if $(env_file),$(env_file),$(COMPOSE_ENV_FILE))" logs -f $(if $(filter all,$(service)),,$(if $(service),$(service),$(APP_SERVICE)))

build:
	docker build -t "$(IMAGE)" .
