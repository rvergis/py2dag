import argparse
import json

from . import parser as dsl_parser
from . import pseudo as pseudo_module
from . import export_svg


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert Python function plan to DAG")
    ap.add_argument("file", help="Python file containing the plan function")
    ap.add_argument("--func", default="plan", help="Function name to parse")
    ap.add_argument("--svg", action="store_true", help="Also export plan.svg")
    args = ap.parse_args()

    plan = dsl_parser.parse_file(args.file, function_name=args.func)
    with open("plan.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    pseudo_code = pseudo_module.generate(plan)
    with open("plan.pseudo", "w", encoding="utf-8") as f:
        f.write(pseudo_code)
    if args.svg:
        export_svg.export(plan, filename="plan.svg")


if __name__ == "__main__":  # pragma: no cover
    main()
