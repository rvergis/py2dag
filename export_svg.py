from typing import Dict, Any

try:
    from graphviz import Digraph
except Exception:  # pragma: no cover
    Digraph = None  # type: ignore


def export(plan: Dict[str, Any], filename: str = "plan.svg") -> str:
    """Export the plan as an SVG using graphviz."""
    if Digraph is None:
        raise RuntimeError("graphviz is required for SVG export")
    graph = Digraph(format="svg")
    for op in plan.get("ops", []):
        graph.node(op["id"], label=op["op"])
        for dep in op.get("deps", []):
            graph.edge(dep, op["id"])
    for out in plan.get("outputs", []):
        out_id = f"out:{out['as']}"
        graph.node(out_id, label=out['as'], shape="note")
        graph.edge(out["from"], out_id)
    graph.render(filename, cleanup=True)
    return filename
