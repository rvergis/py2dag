# py2dag
Convert Python function plans to a DAG (JSON, pseudo, optional SVG).

## Install

- From PyPI (once published):

```
pip install py2dag
```

- From source using Makefile targets (recommended for development):

```
make setup         # create .venv and install deps (SVG extra by default)
```

## Dev Environment via Makefile

- Install Poetry (see poetry docs or `pipx install poetry`).
- From the repo root:

```
poetry install
```

Note: HTML export via Dagre needs no system dependencies. Optional Graphviz SVG export requires the Graphviz system binaries (e.g., `brew install graphviz`).

### Local Virtualenv (.venv)

- Create/update venv and install deps: `make setup`
- Open interactive shell inside venv: `make shell`
- `.venv/` is ignored by git.

## Usage

- Run via Makefile (dev) — generates an interactive Dagre HTML graph:

```
make run FILE=path/to/your_file.py ARGS=--html
```

- Run the installed CLI (after `pip install py2dag`):

```
py2dag path/to/your_file.py --html
```


- Or directly with Python (inside venv):

```
poetry run python cli.py path/to/your_file.py --html
```

This generates `plan.json`, `plan.pseudo`, and if `--html` is used, `plan.html`.

## Tests

Run tests using the Makefile (prints visible with `-s`):

```
make test
```

## Build

Build the package artifacts (wheel and sdist):

```
make build
```

## Releasing to PyPI

This repo includes a GitHub Actions workflow that publishes to PyPI when you push a Git tag like `v0.1.1`.

1) In GitHub repo settings, add a repository secret named `PYPI_API_TOKEN` with your PyPI token (format: `pypi-***`).

2) Bump patch version, create tag, and push it (this triggers the workflow):

```
make release
```

Or do individual steps:

```
make bump-patch
make tag
make push-tags
```

You can also install from the local build with `pip install dist/*.whl`.
