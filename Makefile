.PHONY: setup shell test run build clean version bump-patch tag push-tags release
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

bump-patch:
		@$(PYTHON) scripts/version_utils.py bump

tag:
	@v=$$(make -s version); git tag v$$v
	@echo Tagged v$$v

push-tags:
	@git push --tags

# release: bump patch, tag, and push tags (triggers GitHub Action to publish)
release: tag push-tags
