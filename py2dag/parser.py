import ast
import json
import re
from typing import Any, Dict, List, Optional

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


def parse(source: str, function_name: Optional[str] = None) -> Dict[str, Any]:
    if len(source) > 20_000:
        raise DSLParseError("Source too large")
    module = ast.parse(source)

    def _parse_fn(fn: ast.AST) -> Dict[str, Any]:
        defined: set[str] = set()
        ops: List[Dict[str, Any]] = []
        outputs: List[Dict[str, str]] = []
        settings: Dict[str, Any] = {}

        returned_var: Optional[str] = None
        # Enforce no-args top-level function signature
        try:
            fargs = getattr(fn, "args")  # type: ignore[attr-defined]
            has_params = bool(
                getattr(fargs, "posonlyargs", []) or fargs.args or fargs.vararg or fargs.kwonlyargs or fargs.kwarg
            )
            if has_params:
                raise DSLParseError("Top-level function must not accept parameters")
        except AttributeError:
            # If args not present, ignore
            pass

        def _collect_name_deps(node: ast.AST) -> List[str]:
            names: List[str] = []
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id not in names:
                        names.append(n.id)
            return names
        # type: ignore[attr-defined]
        for i, stmt in enumerate(fn.body):  # type: ignore[attr-defined]
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
                if isinstance(value, ast.Call):
                    op_name = _get_call_name(value.func)

                    deps: List[str] = []

                    def _expand_star_name(varname: str) -> List[str]:
                        # Try to expand a previously packed list/tuple variable into its element deps
                        for prev in reversed(ops):
                            if prev.get("id") == varname:
                                if prev.get("op") in {"PACK.list", "PACK.tuple"}:
                                    return list(prev.get("deps", []))
                                break
                        return [varname]
                    for arg in value.args:
                        if isinstance(arg, ast.Starred):
                            star_val = arg.value
                            if isinstance(star_val, ast.Name):
                                if star_val.id not in defined:
                                    raise DSLParseError(f"Undefined dependency: {star_val.id}")
                                deps.extend(_expand_star_name(star_val.id))
                            elif isinstance(star_val, (ast.List, ast.Tuple)):
                                for elt in star_val.elts:
                                    if not isinstance(elt, ast.Name):
                                        raise DSLParseError("Starred list/tuple elements must be names")
                                    if elt.id not in defined:
                                        raise DSLParseError(f"Undefined dependency: {elt.id}")
                                    deps.append(elt.id)
                            else:
                                raise DSLParseError("*args must be a name or list/tuple of names")
                        elif isinstance(arg, ast.Name):
                            if arg.id not in defined:
                                raise DSLParseError(f"Undefined dependency: {arg.id}")
                            deps.append(arg.id)
                        elif isinstance(arg, (ast.List, ast.Tuple)):
                            for elt in arg.elts:
                                if not isinstance(elt, ast.Name):
                                    raise DSLParseError("List/Tuple positional args must be variable names")
                                if elt.id not in defined:
                                    raise DSLParseError(f"Undefined dependency: {elt.id}")
                                deps.append(elt.id)
                        else:
                            raise DSLParseError("Positional args must be variable names or lists/tuples of names")

                    kwargs: Dict[str, Any] = {}
                    for kw in value.keywords:
                        if kw.arg is None:
                            # **kwargs support: allow dict literal merge, or variable name as dep
                            v = kw.value
                            if isinstance(v, ast.Dict):
                                # Merge literal kwargs
                                lit = _literal(v)
                                for k, val in lit.items():
                                    kwargs[str(k)] = val
                            elif isinstance(v, ast.Name):
                                if v.id not in defined:
                                    raise DSLParseError(f"Undefined dependency: {v.id}")
                                deps.append(v.id)
                            else:
                                raise DSLParseError("**kwargs must be a dict literal or a variable name")
                        else:
                            # Support variable-name keyword args as dependencies; literals remain in args
                            if isinstance(kw.value, ast.Name):
                                name = kw.value.id
                                if name not in defined:
                                    raise DSLParseError(f"Undefined dependency: {name}")
                                deps.append(name)
                            else:
                                kwargs[kw.arg] = _literal(kw.value)

                    ops.append({"id": var_name, "op": op_name, "deps": deps, "args": kwargs})
                elif isinstance(value, ast.JoinedStr):
                    # Minimal f-string support: only variable placeholders
                    deps: List[str] = []
                    parts: List[str] = []
                    for item in value.values:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            parts.append(item.value)
                        elif isinstance(item, ast.FormattedValue) and isinstance(item.value, ast.Name):
                            name = item.value.id
                            if name not in defined:
                                raise DSLParseError(f"Undefined dependency: {name}")
                            deps.append(name)
                            parts.append("{" + str(len(deps) - 1) + "}")
                        else:
                            raise DSLParseError("f-strings may only contain variable names")
                    template = "".join(parts)
                    ops.append({
                        "id": var_name,
                        "op": "TEXT.format",
                        "deps": deps,
                        "args": {"template": template},
                    })
                elif isinstance(value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
                    # Allow assigning literals; also support packing lists/tuples of names
                    try:
                        lit = _literal(value)
                        ops.append({
                            "id": var_name,
                            "op": "CONST.value",
                            "deps": [],
                            "args": {"value": lit},
                        })
                    except DSLParseError:
                        if isinstance(value, (ast.List, ast.Tuple)):
                            elts = value.elts
                            names: List[str] = []
                            for elt in elts:
                                if not isinstance(elt, ast.Name):
                                    raise DSLParseError("Only names allowed in non-literal list/tuple assignment")
                                if elt.id not in defined:
                                    raise DSLParseError(f"Undefined dependency: {elt.id}")
                                names.append(elt.id)
                            kind = "list" if isinstance(value, ast.List) else "tuple"
                            ops.append({
                                "id": var_name,
                                "op": f"PACK.{kind}",
                                "deps": names,
                                "args": {},
                            })
                        else:
                            raise
                elif isinstance(value, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                    # Basic comprehension support: collect name deps and emit a generic comp op
                    name_deps = [n for n in _collect_name_deps(value) if n in defined]
                    # Ensure no undefined names used
                    for n in name_deps:
                        if n not in defined:
                            raise DSLParseError(f"Undefined dependency: {n}")
                    kind = (
                        "listcomp" if isinstance(value, ast.ListComp) else
                        "setcomp" if isinstance(value, ast.SetComp) else
                        "dictcomp" if isinstance(value, ast.DictComp) else
                        "genexpr"
                    )
                    ops.append({
                        "id": var_name,
                        "op": f"COMP.{kind}",
                        "deps": name_deps,
                        "args": {},
                    })
                else:
                    raise DSLParseError("Right hand side must be a call or f-string")
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
            elif isinstance(stmt, ast.Return):
                if i != len(fn.body) - 1:  # type: ignore[index]
                    raise DSLParseError("return must be the last statement")
                if isinstance(stmt.value, ast.Name):
                    var = stmt.value.id
                    if var not in defined:
                        raise DSLParseError(f"Undefined return variable: {var}")
                    returned_var = var
                elif isinstance(stmt.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
                    # Support returning a JSON-serialisable literal (str/num/bool/None, list/tuple, dict)
                    lit = _literal(stmt.value)
                    const_id_base = "return_value"
                    const_id = const_id_base
                    n = 1
                    while const_id in defined:
                        const_id = f"{const_id_base}_{n}"
                        n += 1
                    ops.append({
                        "id": const_id,
                        "op": "CONST.value",
                        "deps": [],
                        "args": {"value": lit},
                    })
                    returned_var = const_id
                else:
                    raise DSLParseError("return must return a variable name or literal")
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.If, ast.Match)):
                # Ignore control flow blocks; only top-level linear statements are modeled
                continue
            elif isinstance(stmt, (ast.Pass,)):
                continue
            else:
                raise DSLParseError("Only assignments, expression calls, and a final return are allowed in function body")

        if not outputs:
            if returned_var is not None:
                outputs.append({"from": returned_var, "as": "return"})
            else:
                raise DSLParseError("At least one output() call required")
        if len(ops) > 200:
            raise DSLParseError("Too many operations")

        # Include the parsed function name for visibility/debugging
        fn_name = getattr(fn, "name", None)  # type: ignore[attr-defined]
        plan: Dict[str, Any] = {"version": 1, "function": fn_name, "ops": ops, "outputs": outputs}
        if settings:
            plan["settings"] = settings
        return plan

    # If a specific function name is provided, use it; otherwise try to auto-detect
    if function_name is not None:
        fn: Optional[ast.AST] = None
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                fn = node
                break
        if fn is None:
            raise DSLParseError(f"Function {function_name!r} not found")
        return _parse_fn(fn)
    else:
        last_err: Optional[Exception] = None
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    return _parse_fn(node)
                except DSLParseError as e:
                    last_err = e
                    continue
        # If we got here, either there are no functions or none matched the DSL
        if last_err is not None:
            raise DSLParseError("No suitable function matched the DSL; specify --func to disambiguate") from last_err
        raise DSLParseError("No function definitions found in source")


def parse_file(filename: str, function_name: Optional[str] = None) -> Dict[str, Any]:
    with open(filename, "r", encoding="utf-8") as f:
        src = f.read()
    return parse(src, function_name=function_name)
