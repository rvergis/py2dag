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

    # Index ops for edge label decisions
    ops = list(plan.get("ops", []))
    op_by_id = {op["id"]: op for op in ops}

    # Nodes
    for op in ops:
        graph.node(op["id"], label=op["op"])

    # Dependency edges with labels showing data/control
    for op in ops:
        for dep in op.get("deps", []):
            src = op_by_id.get(dep)
            label = dep  # default to SSA id
            if src is not None:
                if src.get("op") == "COND.eval":
                    label = "cond"
                elif src.get("op") == "ITER.eval":
                    args = src.get("args", {}) or {}
                    label = str(args.get("target") or "iter")
            graph.edge(dep, op["id"], label=label)
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
