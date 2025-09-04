.PHONY: setup setup-svg setup-venv shell test run build clean version bump-patch tag push-tags release

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

# --- Release helpers ---

version:
	@python3 - <<'PY'
import re, pathlib
p = pathlib.Path('pyproject.toml').read_text(encoding='utf-8')
m = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', p, flags=re.M)
print(m.group(1) if m else '0.0.0')
PY

bump-patch:
	@python3 - <<'PY'
import re, pathlib
path = pathlib.Path('pyproject.toml')
text = path.read_text(encoding='utf-8')
def repl(m):
    major, minor, patch = map(int, m.group(1).split('.'))
    patch += 1
    return f'version = "{major}.{minor}.{patch}"'
new = re.sub(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"', repl, text, count=1)
path.write_text(new, encoding='utf-8')
print('Bumped to:', re.search(r'(?m)^version\s*=\s*"(.*)"', new).group(1))
PY

tag:
	@v=$$(make -s version); git tag v$$v
	@echo Tagged v$$v

push-tags:
	@git push --tags

# release: bump patch, tag, and push tags (triggers GitHub Action to publish)
release: bump-patch tag push-tags
