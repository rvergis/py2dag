import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import parser


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


def test_rejects_fstrings_and_subscripts():
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
