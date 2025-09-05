import pytest
from py2dag import parser


def parse_src(code: str):
    return parser.parse(code)


def test_accepts_async_await_and_attribute_calls():
    code = '''
async def plan():
    a = await AGENTX.op1()
    b = await AGENTX.op2(a, k=1)
    return b
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
    return s
'''
    plan = parse_src(code)
    assert any(op["id"] == "s" and op["op"] == "TEXT.format" for op in plan["ops"])  # type: ignore[index]


def test_rejects_subscripts_even_in_fstrings():
    code = '''
def plan():
    a = AGENT.op()
    s = f"val {a['k']}"
    return a
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
    return b
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
    return a
'''
    plan = parser.parse(code)
    assert len(plan["ops"]) == 1
    assert plan["ops"][0]["id"] == "a"
    assert plan["outputs"][0]["as"] == "return"
    assert plan["function"] == "my_flow"


def test_parses_async_non_standard_function_name_autodetect():
    code = '''
# comment line 1
# comment line 2
# comment line 3
async def my_async_def_fn():
    a = await AGENTX.op1()
    b = await AGENTX.op2(a, k=2)
    return b
'''
    plan = parser.parse(code)
    assert len(plan["ops"]) == 2
    assert plan["ops"][0]["id"] == "a"
    assert plan["ops"][1]["id"] == "b"
    assert plan["outputs"][0]["as"] == "return"
    assert plan["function"] == "my_async_def_fn"


def test_parses_when_comments_precede_function():
    code = '''
# leading comment line 1
# leading comment line 2
def flow_with_comments():
    a = AGENT.op()
    return a
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow_with_comments"
    assert len(plan["ops"]) == 1
    assert plan["ops"][0]["id"] == "a"
    assert plan["outputs"][0]["as"] == "return"


def test_parses_async_with_comments_and_awaits():
    code = '''
# file-level comment A
# file-level comment B

async def flow_async_with_comments():
    # inside comment before first op
    a = await TOOL1.op1()
    # comment between ops
    b = await TOOL2.op2(a, k=3)
    # final comment before output
    return "DONE"
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow_async_with_comments"
    # Ensure the first two ops are parsed correctly
    assert [op["id"] for op in plan["ops"]][:2] == ["a", "b"]
    assert plan["ops"][0]["op"] == "TOOL1.op1"
    assert plan["ops"][1]["op"] == "TOOL2.op2"


def test_parses_async_with_comments_and_return_literal():
    code = '''
# file-level comment A
# file-level comment B

async def flow_async_with_comments():
    # inside comment before first op
    a = await TOOL1.op1()
    # comment between ops
    b = await TOOL2.op2(a, k=3)
    # final comment before return
    return "DONE"
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow_async_with_comments"
    # First two ops as expected, plus a synthesized const op for return literal
    assert [op["id"] for op in plan["ops"]][:2] == ["a", "b"]
    assert plan["ops"][0]["op"] == "TOOL1.op1"
    assert plan["ops"][1]["op"] == "TOOL2.op2"
    # Last op should be the synthesized const op with the literal value
    last = plan["ops"][-1]
    assert last["op"] == "CONST.value"
    assert last["args"]["value"] == "DONE"
    # Outputs should point to that synthesized node with alias 'return'
    assert plan["outputs"][0]["from"] == last["id"]
    assert plan["outputs"][0]["as"] == "return"
