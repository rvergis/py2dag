import pytest
from py2dag import parser


def parse_src(code: str):
    return parser.parse(code)


def test_accepts_async_await_and_attribute_calls():
    code = '''
async def plan():
    a = await AGENTX.op1()
    b = await AGENTX.op2(a, k=1)
    output(b, as_="out.txt")
'''
    plan = parse_src(code)
    assert len(plan["ops"]) == 2
    assert len(plan["outputs"]) == 1
    assert plan["ops"][-1]["id"] == "b"


def test_accepts_fstrings():
    code = '''
def plan():
    a = AGENT.op()
    s = f"val {a}"
    output(s, as_="o.txt")
'''
    plan = parse_src(code)
    assert any(op["id"] == "s" and op["op"] == "TEXT.format" for op in plan["ops"])  # type: ignore[index]


def test_rejects_subscripts_even_in_fstrings():
    code = '''
def plan():
    a = AGENT.op()
    s = f"val {a['k']}"
    output(a, as_="o.txt")
'''
    with pytest.raises(Exception):
        parse_src(code)


def test_rejects_imports_loops_if():
    code = '''
def plan():
    import os
'''
    with pytest.raises(Exception):
        parse_src(code)


def test_rejects_undefined_dep():
    code = '''
def plan():
    b = AGENT.op(a)
    output(b, as_="o.txt")
'''
    with pytest.raises(Exception):
        parse_src(code)


def test_requires_output():
    code = '''
def plan():
    a = AGENT.op()
'''
    with pytest.raises(Exception):
        parse_src(code)


def test_parses_non_standard_function_name_autodetect():
    code = '''
def my_flow():
    a = AGENT.op()
    output(a, as_="o.txt")
'''
    plan = parser.parse(code)
    assert len(plan["ops"]) == 1
    assert plan["ops"][0]["id"] == "a"
    assert plan["outputs"][0]["as"] == "o.txt"
    assert plan["function"] == "my_flow"


def test_parses_async_non_standard_function_name_autodetect():
    code = '''
# comment line 1
# comment line 2
# comment line 3
async def my_async_def_fn():
    a = await AGENTX.op1()
    b = await AGENTX.op2(a, k=2)
    output(b, as_="out.txt")
'''
    plan = parser.parse(code)
    assert len(plan["ops"]) == 2
    assert plan["ops"][0]["id"] == "a"
    assert plan["ops"][1]["id"] == "b"
    assert plan["outputs"][0]["as"] == "out.txt"
    assert plan["function"] == "my_async_def_fn"


def test_parses_when_comments_precede_function():
    code = '''
# leading comment line 1
# leading comment line 2
def flow_with_comments():
    a = AGENT.op()
    output(a, as_="o2.txt")
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow_with_comments"
    assert len(plan["ops"]) == 1
    assert plan["ops"][0]["id"] == "a"
    assert plan["outputs"][0]["as"] == "o2.txt"
