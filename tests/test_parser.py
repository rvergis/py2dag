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


def test_ignores_for_loop_and_parses_return():
    code = '''
def plan():
    a = AGENT.op()
    for i in [1, 2, 3]:
        a = AGENT.op2(a)
        if i == 2:
            break
    return a
'''
    plan = parse_src(code)
    # Loop is ignored; only the initial assignment is captured
    assert [op["id"] for op in plan["ops"]] == ["a"]
    assert plan["outputs"][0]["from"] == "a"
    assert plan["outputs"][0]["as"] == "return"


def test_ignores_async_for_loop_and_parses_return():
    code = '''
async def flow_with_loop():
    a = await TOOL1.op1()
    for i in [1, 2, 3]:
        a = await TOOL1.op2(a)
        if i == 1:
            break
    return a
'''
    plan = parser.parse(code)
    assert [op["id"] for op in plan["ops"]] == ["a"]
    assert plan["outputs"][0]["from"] == "a"
    assert plan["outputs"][0]["as"] == "return"


def test_return_dict_literal_synthesizes_const_node():
    code = '''
def flow_returns_dict():
    a = AGENT.op()
    result = f"ok {a}"
    return {"status": "ok", "value": [1, 2, 3]}
'''
    plan = parser.parse(code)
    assert plan["function"] == "flow_returns_dict"
    # Last op should be the synthesized const op with the dict literal
    last = plan["ops"][-1]
    assert last["op"] == "CONST.value"
    assert last["args"]["value"] == {"status": "ok", "value": [1, 2, 3]}
    assert plan["outputs"][0]["from"] == last["id"]
    assert plan["outputs"][0]["as"] == "return"


def test_generator_pycode():
    code = '''
# comment line 1
# comment line 2
# comment line 3

async def fn1():
    # Step 1
    a = await TOOL1.op1()
    # Step 2
    b = await TOOL2.op2(a)
    # Step 3
    c = await TOOL3.op3(b)
    crossing_info = None
    for i in range(0, 10):
        # Step 4
        d = await TOOL4.op4(c)
        if not d:
            continue
        v1 = d.get("k1")
        v2 = d.get("k2")
        v3 = d.get("k3")
        crossing_info = {
            "k1": v1,
            "k2": v2,
            "k3": v3
        }
        break
    return crossing_info
'''
    plan = parser.parse(code)
    assert plan["function"] == "fn1"
    # Loops are ignored; crossing_info remains the initial None assignment
    assert any(op["id"] == "crossing_info" and op["op"] == "CONST.value" for op in plan["ops"])  # type: ignore[index]
    assert plan["outputs"][0]["from"] == "crossing_info"
    assert plan["outputs"][0]["as"] == "return"


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


def test_describe_scene_sample_parses_correctly():
    code = '''
async def describe_scene_at_50_seconds():
    frame_id = await AGENTYOLO.convert_elapsed_time_to_frame_id(seconds=50.0)
    summary_text = await AGENTLLAVA.summarize_video_at_elapsed_time(et=50)
    approx_coords = await AGENTKLVR.get_approximate_lat_lon_at_elapsed_time(et=50)
    lat = await AGENTKLVR.get_lat(approx_coords)
    lon = await AGENTKLVR.get_lon(approx_coords)
    freeway_name = await AGENTROADY.get_freeway_details_after_elapsed_time(et=50)
    lane_count = await AGENTROADY.get_number_of_lanes_after_elapsed_time(et=50)
    final_summary = f"At 50 seconds into the video, {summary_text} " \
                    f"The vehicle is at coordinates {lat}, {lon} on the {freeway_name}. " \
                    f"There are {lane_count} lanes."
    return final_summary
'''
    plan = parser.parse(code)
    assert plan["function"] == "describe_scene_at_50_seconds"
    assert len(plan["ops"]) == 8
    assert any(op["id"] == "final_summary" and op["op"] == "TEXT.format" for op in plan["ops"])  # type: ignore[index]
    assert plan["outputs"][0]["from"] == "final_summary"
    assert plan["outputs"][0]["as"] == "return"


def test_generator_pycode():
    code = '''
# comment line 1
# comment line 2
# comment line 3

async def fn1():
    # Step 1
    a = await TOOL1.op1()
    # Step 2
    b = await TOOL2.op2(param1=a)
    # Step 3
    c = await TOOL3.op3(param1=b)
    crossing_info = None
    for i in range(0, 10):
        # Step 4
        d = await TOOL4.op4(param1=c, param2=i)
        if not d:
            continue
        v1 = d.get("k1")
        v2 = d.get("k2")
        e = await TOOL5.op5(d)
        v3 = e["k3"]
        crossing_info = {
            "k1": v1,
            "k2": v2,
            "k3": v3,
            "k4": await TOOL5.op5(d)
        }
        break
    if crossing_info is None:
        return { "status": "UNABLE_TO_PARSE", "reason": "No crossing information found" }
    return crossing_info
'''
    plan = parser.parse(code)
    assert plan["function"] == "fn1"
    # Ensure the first three linear ops are parsed in order
    assert [op["op"] for op in plan["ops"]][:3] == [
        "TOOL1.op1",
        "TOOL2.op2",
        "TOOL3.op3",
    ]
    assert [op["id"] for op in plan["ops"]][:3] == ["a", "b", "c"]
    assert any(op["id"] == "crossing_info" and op["op"] == "CONST.value" for op in plan["ops"])  # type: ignore[index]
    assert plan["outputs"][0]["from"] == "crossing_info"
    assert plan["outputs"][0]["as"] == "return"
