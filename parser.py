import ast
import json
import re
from typing import Any, Dict, List

VALID_NAME_RE = re.compile(r'^[a-z_][a-z0-9_]{0,63}$')


class DSLParseError(Exception):
    """Raised when the mini-DSL constraints are violated."""


def _literal(node: ast.AST) -> Any:
    """Return a Python literal from an AST node or raise DSLParseError."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(elt) for elt in node.elts]
    if isinstance(node, ast.Dict):
        return {_literal(k): _literal(v) for k, v in zip(node.keys, node.values)}
    raise DSLParseError("Keyword argument values must be JSON-serialisable literals")


def _get_call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: List[str] = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
            return ".".join(reversed(parts))
    raise DSLParseError("Only simple or attribute names are allowed for operations")


def parse(source: str, function_name: str = "plan") -> Dict[str, Any]:
    if len(source) > 20_000:
        raise DSLParseError("Source too large")
    module = ast.parse(source)
    fn = None
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            fn = node
            break
    if fn is None:
        raise DSLParseError(f"Function {function_name!r} not found")

    defined: set[str] = set()
    ops: List[Dict[str, Any]] = []
    outputs: List[Dict[str, str]] = []
    settings: Dict[str, Any] = {}

    for stmt in fn.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                raise DSLParseError("Assignment targets must be simple names")
            var_name = stmt.targets[0].id
            if not VALID_NAME_RE.match(var_name):
                raise DSLParseError(f"Invalid variable name: {var_name}")
            if var_name in defined:
                raise DSLParseError(f"Duplicate variable name: {var_name}")

            value = stmt.value
            if isinstance(value, ast.Await):
                value = value.value
            if not isinstance(value, ast.Call):
                raise DSLParseError("Right hand side must be a call")
            op_name = _get_call_name(value.func)

            deps: List[str] = []
            for arg in value.args:
                if not isinstance(arg, ast.Name):
                    raise DSLParseError("Positional args must be variable names")
                if arg.id not in defined:
                    raise DSLParseError(f"Undefined dependency: {arg.id}")
                deps.append(arg.id)

            kwargs: Dict[str, Any] = {}
            for kw in value.keywords:
                if kw.arg is None:
                    raise DSLParseError("**kwargs are not allowed")
                kwargs[kw.arg] = _literal(kw.value)

            ops.append({"id": var_name, "op": op_name, "deps": deps, "args": kwargs})
            defined.add(var_name)

        elif isinstance(stmt, ast.Expr):
            call = stmt.value
            if isinstance(call, ast.Await):
                call = call.value
            if not isinstance(call, ast.Call):
                raise DSLParseError("Only call expressions allowed at top level")
            name = _get_call_name(call.func)
            if name == "settings":
                for kw in call.keywords:
                    if kw.arg is None:
                        raise DSLParseError("settings does not accept **kwargs")
                    settings[kw.arg] = _literal(kw.value)
                if call.args:
                    raise DSLParseError("settings only accepts keyword literals")
            elif name == "output":
                if len(call.args) != 1 or not isinstance(call.args[0], ast.Name):
                    raise DSLParseError("output requires a single variable name argument")
                var = call.args[0].id
                if var not in defined:
                    raise DSLParseError(f"Undefined output variable: {var}")
                filename = None
                for kw in call.keywords:
                    if kw.arg in {"as", "as_"}:
                        filename = _literal(kw.value)
                    else:
                        raise DSLParseError("output only accepts 'as' keyword")
                if filename is None or not isinstance(filename, str):
                    raise DSLParseError("output requires as=\"filename\"")
                outputs.append({"from": var, "as": filename})
            else:
                raise DSLParseError("Only settings() and output() calls allowed as expressions")
        else:
            raise DSLParseError("Only assignments and expression calls are allowed in function body")

    if not outputs:
        raise DSLParseError("At least one output() call required")
    if len(ops) > 200:
        raise DSLParseError("Too many operations")

    plan: Dict[str, Any] = {"version": 1, "ops": ops, "outputs": outputs}
    if settings:
        plan["settings"] = settings
    return plan


def parse_file(filename: str, function_name: str = "plan") -> Dict[str, Any]:
    with open(filename, "r", encoding="utf-8") as f:
        src = f.read()
    return parse(src, function_name=function_name)
