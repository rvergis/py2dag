import argparse
import json

from . import parser as dsl_parser
from . import pseudo as pseudo_module
from . import export_svg
import json as _json
import re as _re


def _to_nodes_edges(plan: dict) -> dict:
    """Convert internal plan (with ops/outputs) to explicit nodes/edges.

    Nodes: one per op, plus one per output sink.
    Edges: for each dep -> op.id, with labels similar to exporters; and op.id -> output sink.
    """
    ops = list(plan.get("ops", []))
    outputs = list(plan.get("outputs", []))

    op_by_id = {op["id"]: op for op in ops}

    # Optional remapping of node ids for nicer presentation
    base_id_map: dict[str, str] = {}
    loop_ctx_map: dict[str, str] = {}  # maps 'loop1' -> 'for_loop_1'
    for_count = 0
    for op in ops:
        new_id = op["id"]
        if op.get("op") == "ITER.eval" and (op.get("args") or {}).get("kind") == "for":
            for_count += 1
            new_id = f"for_loop_{for_count}"
            loop_ctx_map[f"loop{for_count}"] = new_id
        base_id_map[op["id"]] = new_id

    def _remap_ctx_suffix(op_id: str) -> str:
        # Replace '@loopN' with '@for_loop_N' when present
        if '@' in op_id:
            base, ctx = op_id.split('@', 1)
            mapped_ctx = loop_ctx_map.get(ctx)
            if mapped_ctx:
                return f"{base}@{mapped_ctx}"
        return op_id

    # Final id map includes context-aware remapping
    id_map: dict[str, str] = {}
    for op in ops:
        oid = op["id"]
        # first apply context suffix remap, then base remap if any
        ctx_remapped = _remap_ctx_suffix(oid)
        id_map[oid] = base_id_map.get(ctx_remapped, ctx_remapped)

    nodes = []
    edges = []

    def _base_name(ssa: str) -> str:
        # Extract base variable name from SSA id like "name_2@ctx" -> "name"
        m = _re.match(r"^([a-z_][a-z0-9_]*?)_\d+(?:@.*)?$", ssa)
        return m.group(1) if m else ssa

    def _expr_for(op: dict) -> str:
        op_name = op.get("op", "")
        deps = op.get("deps", []) or []
        args = op.get("args", {}) or {}
        dep_labels = op.get("dep_labels", []) or []
        # Helper to stringify deps as base names
        dep_names = [_base_name(d) for d in deps]
        # Special-case control/struct ops first
        if op_name == "TEXT.format":
            return f"f\"{args.get('template','')}\""
        if op_name == "CONST.value":
            return _json.dumps(args.get("value"))
        if op_name == "GET.item":
            base = _base_name(deps[0]) if deps else "<unknown>"
            return f"{base}[{_json.dumps(args.get('key'))}]"
        if op_name == "PACK.list":
            return "[" + ", ".join(dep_names) + "]"
        if op_name == "PACK.tuple":
            return "(" + ", ".join(dep_names) + ")"
        if op_name == "PACK.dict":
            keys = (args.get("keys") or [])
            items = []
            for i, k in enumerate(keys):
                val = dep_names[i] if i < len(dep_names) else "<val>"
                items.append(f"{k}: {val}")
            return "{" + ", ".join(items) + "}"
        if op_name == "COND.eval":
            kind = args.get("kind")
            return f"{kind} {args.get('expr')}" if kind else str(args.get('expr'))
        if op_name == "ITER.eval":
            tgt = args.get("target")
            expr = args.get("expr")
            if tgt:
                return f"for {tgt} in {expr}"
            return f"iter {expr}"
        if op_name == "ITER.item":
            return str(args.get("target") or "item")
        if op_name == "PHI":
            return "phi(" + ", ".join(dep_names) + ")"
        if op_name.startswith("COMP."):
            return op_name
        # Generic tool/attribute call ops
        if op_name.endswith(".op") or "." in op_name:
            parts = []
            used_args = set()
            # Encode deps in original order, honoring labels for kwargs and vararg markers
            for i, name in enumerate(dep_names):
                lbl = dep_labels[i] if i < len(dep_labels) else ""
                dep_id = deps[i] if i < len(deps) else ""
                src = op_by_id.get(dep_id)
                if (
                    lbl
                    and src
                    and src.get("op") == "CONST.value"
                    and isinstance(args, dict)
                    and lbl in args
                ):
                    parts.append(f"{lbl}={_json.dumps(args[lbl])}")
                    used_args.add(lbl)
                elif lbl == "*":
                    parts.append(f"*{name}")
                elif lbl == "**":
                    parts.append(f"**{name}")
                elif lbl:  # keyword variable arg
                    parts.append(f"{lbl}={name}")
                else:  # positional
                    parts.append(name)
            # Append literal kwargs (in insertion order)
            for k, v in (args.items() if isinstance(args, dict) else []):
                if k in {"template", "expr", "kind", "keys", "target", "var"} or k in used_args:
                    continue
                parts.append(f"{k}={_json.dumps(v)}")
            return f"{op_name}(" + ", ".join(parts) + ")"
        # Fallback: show op name and dep names
        return f"{op_name}(" + ", ".join(dep_names) + ")"

    def _type_for(op: dict) -> str:
        op_name = op.get("op", "")
        if op_name == "CONST.value":
            return "const"
        if op_name == "TEXT.format":
            return "format"
        if op_name == "GET.item":
            return "get_item"
        if op_name.startswith("PACK."):
            kind = op_name.split(".", 1)[1]
            return f"pack:{kind}"
        if op_name == "COND.eval":
            kind = (op.get("args") or {}).get("kind")
            if kind in {"if", "while"}:
                return kind
            return "cond"
        if op_name == "ITER.eval":
            kind = (op.get("args") or {}).get("kind")
            return "forloop" if kind == "for" else "iter"
        if op_name == "ITER.item":
            return "forloop_item"
        if op_name == "PHI":
            return "phi"
        if op_name == "CTRL.break":
            return "break"
        if op_name.startswith("COMP."):
            comp = op_name.split(".", 1)[1]
            return f"comp:{comp}"
        # Default: treat as a call/tool node
        return "call"

    # Create nodes for ops
    # For friendly IDs, keep execution-order counters per base
    pretty_counters: dict[str, int] = {}

    for op in ops:
        # Compute final node id (may override for pretty IDs)
        op_id = op["id"]
        op_name = op.get("op", "")
        # Choose displayed variable name: prefer loop target for ITER.eval
        var_name = _base_name(op_id)
        if op.get("op") == "ITER.eval":
            tgt = (op.get("args") or {}).get("target")
            if isinstance(tgt, str) and tgt:
                var_name = tgt
        # Start from base remapped id
        node_id = id_map[op_id]
        # If this is a synthetic expression-call (base var 'call'), use op name plus context suffix
        if var_name == "call" and (op_name.endswith(".op") or "." in op_name):
            suffix = ""
            if "@" in node_id:
                suffix = node_id.split("@", 1)[1]
            base_pretty = f"{op_name}@{suffix}" if suffix else op_name
            # Increment execution-order counter and append #N, starting at 1
            n = pretty_counters.get(base_pretty, 0) + 1
            pretty_counters[base_pretty] = n
            node_id = f"{base_pretty}#{n}"
            # Update map so downstream references use the pretty id
            id_map[op_id] = node_id

        # Merge literal kwargs with variable bindings into args map
        merged_args = dict(op.get("args", {}) or {})
        dep_labels = op.get("dep_labels", []) or []
        # track positional index for unlabeled deps
        pos_index = 0
        for idx, dep in enumerate(op.get("deps", []) or []):
            label = dep_labels[idx] if idx < len(dep_labels) else ""
            if not label:
                # positional arg
                merged_args[str(pos_index)] = dep
                pos_index += 1
            elif label not in {"*", "**"}:
                # keyword variable arg
                merged_args[label] = dep
            # ignore '*'/'**' labels in args map; they are reflected by numeric positions or literal kwargs

        # Remap any arg values that reference op ids
        for k, v in list(merged_args.items()):
            if isinstance(v, str):
                vv = id_map.get(v, _remap_ctx_suffix(v))
                merged_args[k] = vv

        # Ensure deterministic ordering of params in args (sorted by key)
        if merged_args:
            merged_args = {k: merged_args[k] for k in sorted(merged_args)}

        # Choose displayed variable name: prefer loop target for ITER.eval
        var_name = _base_name(op["id"])
        if op.get("op") == "ITER.eval":
            tgt = (op.get("args") or {}).get("target")
            if isinstance(tgt, str) and tgt:
                var_name = tgt

        label = op_name
        if op.get("op") == "ITER.eval" and (op.get("args") or {}).get("kind") == "for":
            label = "forloop"
        elif op.get("op") == "ITER.item":
            label = "FORLOOP.item"

        node_obj = {
            "id": node_id,
            "type": _type_for(op),
            "label": label,
            "var": var_name,
            "expr": _expr_for(op),
            "args": merged_args,
        }
        # For control/struct item binders, drop args to avoid redundant control deps
        if op.get("op") == "ITER.item":
            node_obj.pop("args", None)
        nodes.append(node_obj)

    # Create edges for deps
    for op in ops:
        deps = op.get("deps", []) or []
        # Special case: PACK.dict can label edges by key
        keys = []
        if op.get("op") == "PACK.dict":
            keys = list((op.get("args") or {}).get("keys", []) or [])
        dep_labels = op.get("dep_labels", []) or []
        seen = set()
        for idx, dep in enumerate(deps):
            to_id = id_map[op["id"]]
            from_id = id_map.get(dep, _remap_ctx_suffix(dep))
            if (from_id, to_id) in seen:
                continue
            seen.add((from_id, to_id))
            label = (dep_labels[idx] if idx < len(dep_labels) else "") or ""
            src = op_by_id.get(dep)
            if not label:
                if keys and idx < len(keys):
                    label = str(keys[idx])
                elif src is not None:
                    if src.get("op") == "COND.eval":
                        # Label IF branches as then/else based on destination context; keep 'cond' for while
                        kind = (src.get("args") or {}).get("kind")
                        if kind == "if":
                            if "@then" in to_id:
                                label = "then"
                            elif "@else" in to_id:
                                label = "else"
                            else:
                                label = "cond"
                        else:
                            label = "cond"
                    elif src.get("op") == "ITER.eval":
                        label = str((src.get("args") or {}).get("target") or "iter")
            edges.append({"from": from_id, "to": to_id, "label": label})

    # Add explicit true/false edges for `if ...: continue` patterns inside loops
    # When an IF inside a loop has a `continue` body and no explicit else branch,
    # no edges are emitted from the COND node to represent the two control-flow
    # outcomes.  Detect such cases and add synthetic edges so that both the
    # "true" (continue) and "false" paths are visible in the exported graph.
    for idx, op in enumerate(ops):
        if op.get("op") != "COND.eval":
            continue
        oid = op["id"]
        if "@" not in oid:
            continue
        _, ctx = oid.split("@", 1)
        if not ctx.startswith("loop"):
            continue
        from_id = id_map[oid]
        existing = [e for e in edges if e["from"] == from_id]
        # Skip if we already have explicit branch labels from this cond
        if any(e.get("label") in {"then", "else", "true", "false"} for e in existing):
            continue
        # Find first op after this cond within the same loop context
        next_op = None
        for later in ops[idx + 1 :]:
            if later["id"].endswith(f"@{ctx}"):
                next_op = later
                break
        if next_op is not None:
            to_id = id_map[next_op["id"]]
            # If an unlabeled edge already exists, relabel it as the false branch
            updated = False
            for e in existing:
                if e["to"] == to_id:
                    e["label"] = "false"
                    updated = True
                    break
            if not updated:
                edges.append({"from": from_id, "to": to_id, "label": "false"})
        # True branch loops back to the for-loop node itself
        loop_node = loop_ctx_map.get(ctx)
        if loop_node:
            edges.append({"from": from_id, "to": loop_node, "label": "true"})

    # Output nodes and edges
    for out in outputs:
        out_id = f"out:{out['as']}"
        nodes.append({
            "id": out_id,
            "type": "output",
            "label": out["as"],
            "var": out["as"],
            "expr": out["as"],
            "args": {"kind": "output"},
        })
        edges.append({"from": out["from"], "to": out_id})

    graph = {
        "version": plan.get("version", 2),
        "function": plan.get("function"),
        "nodes": nodes,
        "edges": edges,
    }
    if plan.get("settings"):
        graph["settings"] = plan["settings"]
    return graph


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert Python function plan to DAG")
    ap.add_argument("file", help="Python file containing the plan function")
    ap.add_argument("--func", default=None, help="Function name to parse (auto-detect if omitted)")
    ap.add_argument("--svg", action="store_true", help="Also export plan.svg via Graphviz (requires dot)")
    ap.add_argument("--html", action="store_true", help="Also export plan.html via Dagre (no system deps)")
    args = ap.parse_args()

    plan = dsl_parser.parse_file(args.file, function_name=args.func)
    # Write explicit nodes/edges form to plan.json for downstream use
    graph = _to_nodes_edges(plan)
    with open("plan.json", "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    pseudo_code = pseudo_module.generate(plan)
    with open("plan.pseudo", "w", encoding="utf-8") as f:
        f.write(pseudo_code)
    if args.html:
        from . import export_dagre
        export_dagre.export(plan, filename="plan.html")
    elif args.svg:
        try:
            export_svg.export(plan, filename="plan.svg")
        except RuntimeError as e:
            print(f"Warning: SVG export skipped: {e}")


if __name__ == "__main__":  # pragma: no cover
    main()
