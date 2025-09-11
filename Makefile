.PHONY: setup shell test run build clean version patch minor release
.ONESHELL:

# Tooling
POETRY ?= poetry
PYTHON ?= python3
WITH_SVG ?= 1

test:
	$(POETRY) run pytest -s tests -v

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
	mkdir -p .out
	for file in examples/sample1.py examples/sample2.py; do \
		base=$$(basename $$file .py); \
		$(POETRY) run py2dag $$file --html; \
		cp $$file .out/$$base.py; \
		mv plan.json .out/$$base.json; \
		mv plan.pseudo .out/$$base.pseudocode; \
		mv plan.html .out/$$base.html; \
	done
build:
	$(POETRY) build

clean:
	rm -rf __pycache__ .pytest_cache build dist *.egg-info plan.json plan.pseudo plan.svg plan.html .out

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
