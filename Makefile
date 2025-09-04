.PHONY: setup setup-svg setup-venv shell test run build clean

# Tooling
POETRY ?= poetry
PYTHON ?= python3

# Example usage: make run FILE=examples/sample.py ARGS=--svg
FILE ?=
ARGS ?=

test:
	pytest -s tests

setup:
	$(POETRY) install

setup-svg:
	$(POETRY) install --with svg

setup-venv:
	# Create in-project venv at .venv and install deps
	$(POETRY) env use $(PYTHON)
	$(POETRY) install

shell:
	$(POETRY) shell

run:
	$(POETRY) run py2dag $(FILE) $(ARGS)

build:
	$(POETRY) build

clean:
	rm -rf __pycache__ .pytest_cache build dist *.egg-info plan.json plan.pseudo plan.svg
