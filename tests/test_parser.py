import sys
from pathlib import Path

import pytest

# Ensure package root is importable when running tests directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from py2dag import parser, cli


def test_linear_calls_with_ssa():
    code = '''
def flow():
    a = AG.op1()
    b = AG.op2(a, k=1)
    return b
'''
    plan = parser.parse(code)
    assert plan["version"] == 2
    ops = plan["ops"]
    assert ops[0]["op"] == "AG.op1"
    b_op = next(op for op in ops if op["op"] == "AG.op2")
    assert ops[0]["id"] != b_op["id"]
    assert plan["outputs"][0]["from"] == b_op["id"]


def test_const_kwarg_emits_const_node():
    code = '''
def flow():
    a = TOOL1.op1()
    b = TOOL2.op2(a, k=2)
    return b
'''
    plan = parser.parse(code)
    ops = plan["ops"]
    const = next(op for op in ops if op["op"] == "CONST.value" and op["args"].get("value") == 2)
    b_op = next(op for op in ops if op["op"] == "TOOL2.op2")
    assert const["id"] in b_op.get("deps", [])
    idx = b_op["deps"].index(const["id"])
    assert b_op.get("dep_labels", [])[idx] == "k"
    assert b_op.get("args", {}).get("k") == 2


def test_if_merges_with_phi():
    code = '''
def flow():
    a = AG.op()
    if a:
        x = AG.x(a)
    else:
        x = AG.y(a)
    return x
'''
    plan = parser.parse(code)
    ops = plan["ops"]
    assert any(op["op"] == "COND.eval" and op["args"]["kind"] == "if" for op in ops)
    x_ops = [op for op in ops if op["op"] in {"AG.x", "AG.y"}]
    assert len(x_ops) == 2
    phi = next(op for op in ops if op["op"] == "PHI")
    assert len(phi["deps"]) == 2
    assert plan["outputs"][0]["from"] == phi["id"]


def test_for_loop_phi_merge():
    code = '''
def flow():
    x = AG.src()
    for i in range(3):
        x = AG.step(x)
    return x
'''
    plan = parser.parse(code)
    ops = plan["ops"]
    assert any(op["op"] == "ITER.eval" for op in ops)
    step = next(op for op in ops if op["op"] == "AG.step")
    phi = next(op for op in ops if op["op"] == "PHI")
    assert step["id"] in phi["deps"]
    assert plan["outputs"][0]["from"] == phi["id"]


def test_while_loop_phi_merge():
    code = '''
def flow():
    x = AG.src()
    while x:
        x = AG.step(x)
    return x
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    ops = plan["ops"]
    assert any(op["op"] == "COND.eval" and op["args"]["kind"] == "while" for op in ops)
    phi = next(op for op in ops if op["op"] == "PHI")
    assert plan["outputs"][0]["from"] == phi["id"]


def test_fstring_and_literal_return():
    code = '''
def flow():
    a = AG.op()
    s = f"val {a}"
    return {"ok": True}
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    ops = plan["ops"]
    assert any(op["op"] == "TEXT.format" for op in ops)
    last = ops[-1]
    assert last["op"] == "CONST.value"
    assert plan["outputs"][0]["from"] == last["id"]


def test_settings_output_and_undefined_dep():
    code = '''
def flow():
    settings(timeout=30, mode="fast")
    a = AG.op()
    output(a, as_="o.txt")
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    assert plan.get("settings") == {"timeout": 30, "mode": "fast"}
    assert plan["outputs"][0]["as"] == "o.txt"
    assert plan["outputs"][0]["from"].endswith("_1")

    bad = '''
def flow():
    b = AG.op(a)
    return b
'''
    with pytest.raises(Exception):
        parser.parse(bad)


def test_comprehension_emits_comp_op_and_deps_ssa():
    code = '''
def flow():
    a = AG.src()
    xs = [v for v in a]
    return a
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    comp = next(op for op in plan["ops"] if op["op"].startswith("COMP."))
    assert len(comp["deps"]) == 1


def test_for_each():
    code = '''
async def flow():
    a = AG1.src()
    xs = await AG1.op(param1=a, param2=42)
    crossing_info = None
    for x in xs:
        AG3.proc(x)
        crossed = await AG4.op2(x)
        if not crossed:
            continue
        approx_time = await AG3.op(x)
        data = await AG4.op(approx_time)
        lat = data["sensor_lat"]
        lon = data["sensor_lon"]
        AG4.proc(approx_time)
        crossing_info = {
            "approx_time": approx_time,
            "details": await AG5.op3(approx_time),
            "item": x,
            "lat": lat,
            "lon": lon,
        }
    return crossing_info
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    comp = next(op for op in plan["ops"] if op["op"].startswith("COMP."))
    assert len(comp["deps"]) == 1
    field_op = next(op for op in plan["ops"] if op["op"] == "AG5.op3")
    assert field_op.get("await") is True


def test_break_node_type():
    code = '''
# Test for break node type
async def flow():
    """
        This is a test for the break node type.
    """
    a = AG1.src()
    xs = await AG1.op(param1=a, param2=42)
    crossing_info = None
    for x in xs:
        AG3.proc(x)
        crossed = await AG4.op2(x)
        if not crossed:
            continue
        approx_time = await AG3.op(x)
        data = await AG4.op(approx_time)
        lat = data["sensor_lat"]
        lon = data["sensor_lon"]
        AG4.proc(approx_time)
        crossing_info = {
            "approx_time": approx_time,
            "details": await AG5.op3(approx_time),
            "item": x,
            "lat": lat,
            "lon": lon,
        }
        break
    return crossing_info
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    graph = cli._to_nodes_edges(plan)
    assert any(node["type"] == "break" for node in graph["nodes"])


def test_comments():
    code = '''
# Line 1
# Line 2
# Line 3
# Line 4
# Line 5

async def flow():
    # get ids
    ids = await AG1.get_ids()
    a_ids = await AG2.get_ids()
    b_ids = await AG3.get_ids()
    # merge ids
    all_ids = await AG4.merge_list([ids, a_ids, b_ids])    
    crossing_info = None
    for x in xs:
        AG3.proc(x)
        crossed = await AG4.op2(x)
        if not crossed:
            continue
        approx_time = await AG3.op(x)
        data = await AG4.op(approx_time)
        lat = data["sensor_lat"]
        lon = data["sensor_lon"]
        AG4.proc(approx_time)
        crossing_info = {
            "approx_time": approx_time,
            "details": await AG5.op3(approx_time),
            "item": x,
            "lat": lat,
            "lon": lon,
        }
        break
    if crossing_info is None:
        return { "status": "UNABLE_TO_PROCEED", "reason": "No valid crossing information found." }
    return crossing_info
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow"
    graph = cli._to_nodes_edges(plan)
    assert any(node["type"] == "break" for node in graph["nodes"])

