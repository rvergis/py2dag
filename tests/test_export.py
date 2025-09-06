import json
from pathlib import Path
import sys

import pytest

# Ensure the package root is importable when tests are executed directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from py2dag import parser
from py2dag import cli


def _export_json(plan, out_dir: Path, name: str) -> Path:
    """Helper to write a DAG JSON file for the given plan."""
    outfile = out_dir / name
    data = cli._to_nodes_edges(plan)
    outfile.write_text(json.dumps(data), encoding="utf-8")
    return outfile


def _plan_simple():
    code = '''
def flow():
    a = AG.op()
    return a
'''
    return parser.parse(code)


def test_export_html():
    from py2dag import export_dagre

    plan = _plan_simple()
    out_dir = Path('.out'); out_dir.mkdir(exist_ok=True)
    outfile = out_dir / "plan.html"
    path = export_dagre.export(plan, filename=str(outfile))
    assert path == str(outfile)
    assert outfile.exists()
    text = outfile.read_text(encoding="utf-8")
    # Basic sanity: embedded plan JSON is present
    assert '"version": 2' in text
    assert plan["function"] in text

    # Also write out the DAG JSON representation
    json_file = _export_json(plan, out_dir, "plan.json")
    assert json_file.exists()


def test_export_svg():
    from py2dag import export_svg

    plan = _plan_simple()
    out_dir = Path('.out'); out_dir.mkdir(exist_ok=True)
    outfile = out_dir / "plan.svg"
    try:
        path = export_svg.export(plan, filename=str(outfile))
    except RuntimeError:
        pytest.skip("Graphviz not available; skipping SVG export test")
    assert path == str(outfile)
    assert outfile.exists()
    content = outfile.read_text(encoding="utf-8", errors="ignore").lower()
    assert "<svg" in content

    # Also ensure the DAG JSON is produced
    json_file = _export_json(plan, out_dir, "plan.json")
    assert json_file.exists()


def _plan_kitchen_sink():
    code = '''
def kitchen_sink():
    settings(timeout=45, mode="fast")
    a = TOOL1.op1()
    b = TOOL2.op2(a, k=2)
    if COND.is_ok(b):
        c = TOOL3.op3(b)
    else:
        c = TOOL3.op4(b)
    x = 0
    for i in range(3):
        c = TOOL4.step(c)
        if COND.more(c):
            d = TOOL5.join(c)
        else:
            d = TOOL5.alt(c)
        c = TOOL6.post(d)
    while c:
        c = TOOL7.finalize(c)
    output(c, as_="result.txt")
'''
    return parser.parse(code)


def test_export_html_kitchen_sink():
    from py2dag import export_dagre

    plan = _plan_kitchen_sink()
    out_dir = Path('.out'); out_dir.mkdir(exist_ok=True)
    outfile = out_dir / "kitchen_sink.html"
    path = export_dagre.export(plan, filename=str(outfile))
    assert outfile.exists() and path == str(outfile)
    text = outfile.read_text(encoding="utf-8")
    # Expect various labels to be present
    assert "TOOL1.op1" in text
    assert "FOR " in text or "ITER.eval" in text
    assert "IF " in text or "COND.eval" in text
    assert "PHI" in text

    json_file = _export_json(plan, out_dir, "kitchen_sink.json")
    assert json_file.exists()


def test_export_svg_kitchen_sink():
    from py2dag import export_svg

    plan = _plan_kitchen_sink()
    out_dir = Path('.out'); out_dir.mkdir(exist_ok=True)
    outfile = out_dir / "kitchen_sink.svg"
    try:
        export_svg.export(plan, filename=str(outfile))
    except RuntimeError:
        pytest.skip("Graphviz not available; skipping SVG export test")
    content = outfile.read_text(encoding="utf-8", errors="ignore").lower()
    assert "<svg" in content

    json_file = _export_json(plan, out_dir, "kitchen_sink.json")
    assert json_file.exists()
