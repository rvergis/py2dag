from typing import Dict, Any

from .colors import color_for

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
    # Top-down layout with a bounding box around the graph
    graph.attr(rankdir="TB")
    graph.attr("graph", margin="0.2", pad="0.3", color="#bbb")

    # Index ops for edge label decisions
    ops = list(plan.get("ops", []))
    op_by_id = {op["id"]: op for op in ops}

    # Nodes
    for op in ops:
        graph.node(
            op["id"],
            label=op["op"],
            style="filled",
            fillcolor=color_for(op["op"]),
        )

    # Dependency edges with labels showing data/control
    for op in ops:
        dep_labels = op.get("dep_labels", []) or []
        seen = set()
        for idx, dep in enumerate(op.get("deps", []) or []):
            pair = (dep, op["id"]) 
            if pair in seen:
                continue
            seen.add(pair)
            src = op_by_id.get(dep)
            label = (dep_labels[idx] if idx < len(dep_labels) else "") or ""
            if not label:
                if op.get("op") == "PACK.dict":
                    keys = (op.get("args", {}) or {}).get("keys", []) or []
                    if idx < len(keys):
                        label = str(keys[idx])
                elif src is not None:
                    if src.get("op") == "COND.eval":
                        const_args = src.get("args", {}) or {}
                        if const_args.get("kind") == "if":
                            dest_id = op.get("id", "")
                            if "@then" in dest_id:
                                label = "then"
                            elif "@else" in dest_id:
                                label = "else"
                            else:
                                label = "cond"
                        else:
                            label = "cond"
                    elif src.get("op") == "ITER.eval":
                        args = src.get("args", {}) or {}
                        label = str(args.get("target") or "iter")
            graph.edge(dep, op["id"], label=label or dep)
    for out in plan.get("outputs", []):
        out_id = f"out:{out['as']}"
        graph.node(
            out_id,
            label=out['as'],
            shape="note",
            style="filled",
            fillcolor=color_for("output"),
        )
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
