# py2dag
Convert Python function plans to a DAG (JSON, pseudo, optional SVG).

## Install

- From PyPI (once published):

```
pip install py2dag
```

- From a local checkout (editable):

```
pip install -e .
```

- From a local checkout (wheel/sdist):

```
pip install .
```

- With Poetry:

```
poetry install
```

## Poetry Setup

- Install Poetry (see poetry docs or `pipx install poetry`).
- From the repo root:

```
poetry install
```

Optional: to enable SVG export support (Python `graphviz`), install extras:

```
poetry install --with svg
```

Note: SVG export also requires the Graphviz system binaries (e.g., `brew install graphviz`).

## Local Virtualenv (.venv)

This project configures Poetry to create an in-project virtualenv at `.venv` (see `poetry.toml`).

- Create/update the venv and install deps:

```
make setup-venv
```

- Open an interactive shell in that venv:

```
make shell
```

`.venv/` is ignored by git.

## Usage

- Run the installed CLI:

```
py2dag path/to/your_file.py --svg
```

- Or via Poetry:

```
poetry run py2dag path/to/your_file.py --svg
```

or directly with Python:

```
poetry run python cli.py path/to/your_file.py --svg
```

This generates `plan.json`, `plan.pseudo`, and if `--svg` is used, `plan.svg`.

Alternatively, using the Makefile:

```
make run FILE=path/to/your_file.py ARGS=--svg
```

## Tests

- Run tests with prints visible:

```
poetry run pytest -s tests
```

Or using the Makefile target (uses `-s`):

```
poetry run make test
```

## Makefile Commands

- `make setup`: install dependencies with Poetry
- `make setup-svg`: install with the `svg` extra (Python `graphviz`)
- `make setup-venv`: create/use local `.venv` and install deps
- `make shell`: activate the Poetry virtualenv shell
- `make run FILE=... ARGS=...`: run the CLI (`py2dag`) with optional args
- `make test`: run tests with `-s` to show `print()` output
- `make build`: build the package via Poetry
- `make clean`: remove caches, build artifacts, and generated plan files

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

You can also build locally:

```
make build
```
