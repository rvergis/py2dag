import pytest
from py2dag import parser


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
    assert ops[1]["op"] == "AG.op2"
    assert ops[0]["id"] != ops[1]["id"]
    assert plan["outputs"][0]["from"] == ops[1]["id"]


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
        AG4.proc(approx_time)
        crossing_info = {
            "approx_time": approx_time,
            "details": await AG5.op3(approx_time),
            "item": x
        }
    return crossing_info
'''
    plan = parser.parse(code)
    comp = next(op for op in plan["ops"] if op["op"].startswith("COMP."))
    assert len(comp["deps"]) == 1

