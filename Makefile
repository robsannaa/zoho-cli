.DEFAULT_GOAL := help
PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF   := .venv/bin/ruff

.PHONY: help install test lint fmt fmt-check ci

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install     Install package + dev deps in .venv"
	@echo "  test        Run tests"
	@echo "  lint        Run ruff linter"
	@echo "  fmt         Auto-format code with ruff"
	@echo "  fmt-check   Check formatting (no changes)"
	@echo "  ci          fmt-check + lint + test"

install:
	uv venv --python 3.11
	uv pip install -e ".[dev]"

test:
	$(PYTEST) tests/ -v

lint:
	$(RUFF) check zoho_cli/

fmt:
	$(RUFF) format zoho_cli/ tests/

fmt-check:
	$(RUFF) format --check zoho_cli/ tests/

ci: fmt-check lint test
