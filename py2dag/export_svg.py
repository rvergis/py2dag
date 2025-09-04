from typing import Dict, Any

try:
    from graphviz import Digraph
except Exception:  # pragma: no cover
    Digraph = None  # type: ignore

try:  # optional: only available when graphviz is installed
    from graphviz.backend.execute import ExecutableNotFound  # type: ignore
except Exception:  # pragma: no cover
    ExecutableNotFound = None  # type: ignore


def export(plan: Dict[str, Any], filename: str = "plan.svg") -> str:
    """Export the plan as an SVG using graphviz.

    Writes a true SVG file at `filename`. If Graphviz system binaries are
    missing, raises RuntimeError with a helpful message. This avoids leaving a
    stray DOT file named `plan.svg` when rendering fails.
    """
    if Digraph is None:
        raise RuntimeError("Python package 'graphviz' is required for SVG export")

    graph = Digraph(format="svg")
    for op in plan.get("ops", []):
        graph.node(op["id"], label=op["op"])
        for dep in op.get("deps", []):
            graph.edge(dep, op["id"])
    for out in plan.get("outputs", []):
        out_id = f"out:{out['as']}"
        graph.node(out_id, label=out['as'], shape="note")
        graph.edge(out["from"], out_id)

    try:
        # Use pipe() to obtain SVG bytes directly so we only write the
        # destination file on successful rendering.
        svg_bytes = graph.pipe(format="svg")
    except Exception as e:  # pragma: no cover - depends on local system
        if ExecutableNotFound is not None and isinstance(e, ExecutableNotFound):
            raise RuntimeError(
                "Graphviz 'dot' executable not found. Install Graphviz (e.g., 'brew install graphviz' on macOS) "
                "or run without --svg."
            ) from e
        raise

    with open(filename, "wb") as f:
        f.write(svg_bytes)
    return filename
