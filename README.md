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

Notes:
- HTML export uses Dagre via CDN (d3.js + dagre-d3). No local system deps, but an internet connection is required when opening `plan.html`. If you are offline or behind a firewall, the page will show a message; vendor the JS locally or open with internet access.
- Optional Graphviz SVG export (`--svg`) requires Graphviz system binaries (e.g., `brew install graphviz`).

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

- Function name: By default the tool auto-detects a suitable function in the file. To target a specific function, pass `--func NAME`.

### Offline HTML (no internet)

`plan.html` references d3 and dagre-d3 from CDNs. To view graphs fully offline, download those files and place them next to `plan.html`, then edit the two `<script>` tags in `py2dag/export_dagre.py` to point at your local copies.

Example (download once):

```
wget https://d3js.org/d3.v5.min.js -O d3.v5.min.js
wget https://unpkg.com/dagre-d3@0.6.4/dist/dagre-d3.min.js -O dagre-d3.min.js
```

Then update the script tags to `./d3.v5.min.js` and `./dagre-d3.min.js` and regenerate `plan.html`.

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

2) Bump patch version, commit, and tag locally; then push tags to trigger the workflow:

```
make patch        # bumps version, commits, and tags vX.Y.Z
make release      # pushes commits and tags to GitHub (triggers publish)
```

Or push tags manually:

```
git push --tags
```

You can also install from the local build with `pip install dist/*.whl`.
