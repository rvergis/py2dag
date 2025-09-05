.PHONY: setup shell test run build clean version patch minor release
.ONESHELL:

# Tooling
POETRY ?= poetry
PYTHON ?= python3
WITH_SVG ?= 1

# Example usage: make run FILE=examples/sample.py ARGS="--html --func describe_scene_at_50_seconds"
FILE ?= examples/sample.py
ARGS ?= --html --func describe_scene_at_50_seconds

test:
	$(POETRY) run pytest -s tests

setup:
	# Ensure in-project .venv and install dependencies (optionally with svg extra)
	$(POETRY) config virtualenvs.in-project true --local
	$(POETRY) env use $(PYTHON)
	@if [ "$(WITH_SVG)" = "1" ]; then \
		$(POETRY) install --extras svg; \
	else \
		$(POETRY) install; \
	fi

shell:
	$(POETRY) shell

run:
	$(POETRY) run py2dag $(FILE) $(ARGS)

build:
	$(POETRY) build

clean:
	rm -rf __pycache__ .pytest_cache build dist *.egg-info plan.json plan.pseudo plan.svg

# --- Release helpers ---

version:
		@$(PYTHON) scripts/version_utils.py print

patch:
	@$(PYTHON) scripts/version_utils.py bump
	@v=$$(make -s version); \
	  git add pyproject.toml; \
	  git commit -m "chore(release): v$$v"; \
	  git tag v$$v; \
	  echo "Bumped, committed, and tagged v$$v"

minor:
	@$(PYTHON) scripts/version_utils.py minor
	@v=$$(make -s version); \
	  git add pyproject.toml; \
	  git commit -m "chore(release): v$$v"; \
	  git tag v$$v; \
	  echo "Bumped minor, committed, and tagged v$$v"

# release: push commits and tags (triggers GitHub Action to publish)
release:
	@git push
	@git push --tags
