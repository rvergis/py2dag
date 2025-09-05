import argparse
import json

from . import parser as dsl_parser
from . import pseudo as pseudo_module
from . import export_svg


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert Python function plan to DAG")
    ap.add_argument("file", help="Python file containing the plan function")
    ap.add_argument("--func", default=None, help="Function name to parse (auto-detect if omitted)")
    ap.add_argument("--svg", action="store_true", help="Also export plan.svg via Graphviz (requires dot)")
    ap.add_argument("--html", action="store_true", help="Also export plan.html via Dagre (no system deps)")
    args = ap.parse_args()

    plan = dsl_parser.parse_file(args.file, function_name=args.func)
    with open("plan.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
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
