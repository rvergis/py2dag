import pytest

from py2dag import parser


def _plan_simple():
    code = '''
def flow():
    a = AG.op()
    return a
'''
    return parser.parse(code)


def test_export_html(tmp_path):
    from py2dag import export_dagre

    plan = _plan_simple()
    outfile = tmp_path / "plan.html"
    path = export_dagre.export(plan, filename=str(outfile))
    assert path == str(outfile)
    assert outfile.exists()
    text = outfile.read_text(encoding="utf-8")
    # Basic sanity: embedded plan JSON is present
    assert '"version": 2' in text
    assert plan["function"] in text


def test_export_svg(tmp_path):
    from py2dag import export_svg

    plan = _plan_simple()
    outfile = tmp_path / "plan.svg"
    try:
        path = export_svg.export(plan, filename=str(outfile))
    except RuntimeError:
        pytest.skip("Graphviz not available; skipping SVG export test")
    assert path == str(outfile)
    assert outfile.exists()
    content = outfile.read_text(encoding="utf-8", errors="ignore").lower()
    assert "<svg" in content

