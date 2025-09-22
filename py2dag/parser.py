import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Set

VALID_NAME_RE = re.compile(r'^[a-z_][a-z0-9_]{0,63}$')


class DSLParseError(Exception):
    """Raised when the mini-DSL constraints are violated."""


def _literal(node: ast.AST) -> Any:
    """Return a Python literal from an AST node or raise DSLParseError."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                try:
                    expr = ast.unparse(value.value)  # type: ignore[attr-defined]
                except Exception:
                    expr = "?"
                parts.append("{" + expr + "}")
            else:
                raise DSLParseError("Keyword argument values must be JSON-serialisable literals")
        return "".join(parts)
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
            pass

        # SSA state
        versions: Dict[str, int] = {}
        latest: Dict[str, str] = {}
        context_suffix: str = ""
        ctx_counts: Dict[str, int] = {"if": 0, "loop": 0, "while": 0, "except": 0}
        loop_depth = 0

        def _ssa_new(name: str) -> str:
            if not VALID_NAME_RE.match(name):
                raise DSLParseError(f"Invalid variable name: {name}")
            versions[name] = versions.get(name, 0) + 1
            base = f"{name}_{versions[name]}"
            ssa = f"{base}@{context_suffix}" if context_suffix else base
            latest[name] = ssa
            return ssa

        def _ssa_get(name: str) -> str:
            if name not in latest:
                raise DSLParseError(f"Undefined dependency: {name}")
            return latest[name]

        def _collect_name_loads(node: ast.AST) -> List[str]:
            names: List[str] = []
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id not in names:
                        names.append(n.id)
            return names

        def _collect_value_deps(node: ast.AST) -> List[str]:
            """Collect variable name dependencies from an expression, excluding callee names in Call.func.

            For example, for range(n) -> ['n'] (not 'range'). For cond(a) -> ['a'] (not 'cond').
            For obj.attr -> ['obj'].
            """
            callees: set[str] = set()

            def mark_callee(func: ast.AST):
                for n in ast.walk(func):
                    if isinstance(n, ast.Name):
                        callees.add(n.id)

            # First collect callee name ids appearing under Call.func
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    mark_callee(n.func)

            # Then collect normal loads and drop any that are marked as callees
            deps: List[str] = []
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id not in callees and n.id not in deps and n.id in latest:
                        deps.append(n.id)
            return deps

        def _stringify(node: ast.AST) -> str:
            try:
                return ast.unparse(node)  # type: ignore[attr-defined]
            except Exception:
                return node.__class__.__name__

        def _emit_assign_from_call(var_name: str, call: ast.Call, awaited: bool = False) -> str:
            op_name = _get_call_name(call.func)
            deps: List[str] = []
            dep_labels: List[str] = []

            def _expand_star_name(ssa_var: str) -> List[str]:
                # Expand if previous op was a PACK.*
                for prev in reversed(ops):
                    if prev.get("id") == ssa_var and prev.get("op") in {"PACK.list", "PACK.tuple"}:
                        return list(prev.get("deps", []))
                return [ssa_var]

            for idx, arg in enumerate(call.args):
                if isinstance(arg, ast.Starred):
                    star_val = arg.value
                    if isinstance(star_val, ast.Name):
                        expanded = _expand_star_name(_ssa_get(star_val.id))
                        deps.extend(expanded)
                        dep_labels.extend(["*"] * len(expanded))
                    elif isinstance(star_val, (ast.List, ast.Tuple)):
                        for elt in star_val.elts:
                            if not isinstance(elt, ast.Name):
                                raise DSLParseError("Starred list/tuple elements must be names")
                            deps.append(_ssa_get(elt.id))
                            dep_labels.append("*")
                    else:
                        raise DSLParseError("*args must be a name or list/tuple of names")
                elif isinstance(arg, ast.Name):
                    deps.append(_ssa_get(arg.id))
                    dep_labels.append("")
                elif isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        if not isinstance(elt, ast.Name):
                            raise DSLParseError("List/Tuple positional args must be variable names")
                        deps.append(_ssa_get(elt.id))
                        dep_labels.append("")
                else:
                    # Allow literal positional arguments by emitting a CONST node
                    try:
                        lit = _literal(arg)
                    except DSLParseError:
                        try:
                            val_id = _emit_value(f"{var_name}_arg{idx}", arg)
                        except DSLParseError as inner_exc:
                            raise DSLParseError(
                                "Positional args must be variable names or lists/tuples of names or literals"
                            ) from inner_exc
                        deps.append(val_id)
                        dep_labels.append("")
                    else:
                        const_id = _ssa_new(f"{var_name}_arg{idx}")
                        ops.append({
                            "id": const_id,
                            "op": "CONST.value",
                            "deps": [],
                            "args": {"value": lit},
                        })
                        deps.append(const_id)
                        dep_labels.append("")

            kwargs: Dict[str, Any] = {}
            for kw in call.keywords:
                if kw.arg is None:
                    v = kw.value
                    if isinstance(v, ast.Dict):
                        lit = _literal(v)
                        for k, val in lit.items():
                            kwargs[str(k)] = val
                    elif isinstance(v, ast.Name):
                        deps.append(_ssa_get(v.id))
                        dep_labels.append("**")
                    else:
                        raise DSLParseError("**kwargs must be a dict literal or a variable name")
                else:
                    if isinstance(kw.value, ast.Name):
                        deps.append(_ssa_get(kw.value.id))
                        dep_labels.append(kw.arg or "")
                    else:
                        try:
                            lit = _literal(kw.value)
                        except DSLParseError:
                            val_id = _emit_value(f"{var_name}_{kw.arg}", kw.value)
                            deps.append(val_id)
                            dep_labels.append(kw.arg or "")
                        else:
                            kwargs[kw.arg] = lit
                            const_id = _ssa_new(f"{var_name}_{kw.arg}")
                            ops.append(
                                {
                                    "id": const_id,
                                    "op": "CONST.value",
                                    "deps": [],
                                    "args": {"value": lit},
                                }
                            )
                            deps.append(const_id)
                            dep_labels.append(kw.arg or "")

            ssa = _ssa_new(var_name)
            op: Dict[str, Any] = {"id": ssa, "op": op_name, "deps": deps, "args": kwargs, "dep_labels": dep_labels}
            if awaited:
                op["await"] = True
            ops.append(op)
            return ssa

        def _emit_expr_call(call: ast.Call, awaited: bool = False) -> str:
            """Emit a node for a bare expression call (no assignment)."""
            return _emit_assign_from_call("call", call, awaited)

        def _emit_assign_from_fstring(var_name: str, fstr: ast.JoinedStr) -> str:
            deps: List[str] = []
            parts: List[str] = []
            for item in fstr.values:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    parts.append(item.value)
                elif isinstance(item, ast.FormattedValue) and isinstance(item.value, ast.Name):
                    deps.append(_ssa_get(item.value.id))
                    parts.append("{" + str(len(deps) - 1) + "}")
                else:
                    raise DSLParseError("f-strings may only contain variable names")
            template = "".join(parts)
            ssa = _ssa_new(var_name)
            ops.append({
                "id": ssa,
                "op": "TEXT.format",
                "deps": deps,
                "args": {"template": template},
            })
            return ssa

        def _emit_assign_from_literal_or_pack(var_name: str, value: ast.AST) -> str:
            try:
                lit = _literal(value)
                ssa = _ssa_new(var_name)
                ops.append({
                    "id": ssa,
                    "op": "CONST.value",
                    "deps": [],
                    "args": {"value": lit},
                })
                return ssa
            except DSLParseError:
                if isinstance(value, (ast.List, ast.Tuple)):
                    elts = value.elts
                    deps: List[str] = []
                    for elt in elts:
                        if not isinstance(elt, ast.Name):
                            raise DSLParseError("Only names allowed in non-literal list/tuple assignment")
                        deps.append(_ssa_get(elt.id))
                    kind = "list" if isinstance(value, ast.List) else "tuple"
                    ssa = _ssa_new(var_name)
                    ops.append({
                        "id": ssa,
                        "op": f"PACK.{kind}",
                        "deps": deps,
                        "args": {},
                    })
                    return ssa
                if isinstance(value, ast.Dict):
                    # Support dict with values from names/calls or literals by synthesizing nodes
                    keys: List[str] = []
                    deps: List[str] = []
                    for k_node, v_node in zip(value.keys, value.values):
                        k_str = _literal(k_node)
                        if not isinstance(k_str, (str, int, float, bool)):
                            k_str = str(k_str)
                        keys.append(str(k_str))
                        if isinstance(v_node, ast.Name):
                            deps.append(_ssa_get(v_node.id))
                        elif isinstance(v_node, ast.Await):
                            inner = v_node.value
                            if not isinstance(inner, ast.Call):
                                raise DSLParseError("await must wrap a call in dict value")
                            tmp_id = _emit_assign_from_call(f"{var_name}_field", inner, awaited=True)
                            deps.append(tmp_id)
                        elif isinstance(v_node, ast.Call):
                            tmp_id = _emit_assign_from_call(f"{var_name}_field", v_node)
                            deps.append(tmp_id)
                        else:
                            # Synthesize const for literal or arbitrary expression value
                            try:
                                lit_val = _literal(v_node)
                            except DSLParseError:
                                try:
                                    lit_val = ast.unparse(v_node)  # type: ignore[attr-defined]
                                except Exception:
                                    lit_val = v_node.__class__.__name__
                            tmp = _ssa_new(f"{var_name}_lit")
                            ops.append({
                                "id": tmp,
                                "op": "CONST.value",
                                "deps": [],
                                "args": {"value": lit_val},
                            })
                            deps.append(tmp)
                    ssa = _ssa_new(var_name)
                    ops.append({
                        "id": ssa,
                        "op": "PACK.dict",
                        "deps": deps,
                        "args": {"keys": keys},
                    })
                    return ssa
                raise

        def _emit_assign_from_comp(var_name: str, node: ast.AST) -> str:
            name_deps = [n for n in _collect_name_loads(node) if n in latest]
            for n in name_deps:
                if n not in latest:
                    raise DSLParseError(f"Undefined dependency: {n}")
            kind = (
                "listcomp" if isinstance(node, ast.ListComp) else
                "setcomp" if isinstance(node, ast.SetComp) else
                "dictcomp" if isinstance(node, ast.DictComp) else
                "genexpr"
            )
            deps = [_ssa_get(n) for n in name_deps]
            ssa = _ssa_new(var_name)
            ops.append({
                "id": ssa,
                "op": f"COMP.{kind}",
                "deps": deps,
                "args": {},
            })
            return ssa

        def _emit_assign_from_subscript(var_name: str, node: ast.Subscript) -> str:
            # Support name[key] where key is a JSON-serialisable literal
            base = node.value
            if not isinstance(base, ast.Name):
                raise DSLParseError("Subscript base must be a variable name")
            # Extract slice expression across Python versions
            sl = getattr(node, 'slice', None)
            # In Python >=3.9, slice is the actual node; before it may be ast.Index
            if hasattr(ast, 'Index') and isinstance(sl, getattr(ast, 'Index')):  # type: ignore[attr-defined]
                sl = sl.value  # type: ignore[assignment]
            key = _literal(sl)  # may raise if not literal
            ssa = _ssa_new(var_name)
            ops.append({
                "id": ssa,
                "op": "GET.item",
                "deps": [_ssa_get(base.id)],
                "args": {"key": key},
            })
            return ssa

        def _emit_assign_to_subscript(target: ast.Subscript, value: ast.AST) -> str:
            """Emit a SET.item node for an assignment like ``name[key] = value``."""
            base = target.value
            if not isinstance(base, ast.Name):
                raise DSLParseError("Subscript base must be a variable name")
            # Extract slice expression across Python versions
            sl = getattr(target, "slice", None)
            if hasattr(ast, "Index") and isinstance(sl, getattr(ast, "Index")):  # type: ignore[attr-defined]
                sl = sl.value  # type: ignore[assignment]
            key = _literal(sl)

            val_id = _emit_value(f"{base.id}_item", value)

            base_id = _ssa_get(base.id)
            ssa = _ssa_new(base.id)
            ops.append({
                "id": ssa,
                "op": "SET.item",
                "deps": [base_id, val_id],
                "args": {"key": key},
            })
            return ssa

        def _emit_cond(node: ast.AST, kind: str = "if") -> str:
            expr = _stringify(node)
            deps = [_ssa_get(n) for n in _collect_value_deps(node)]
            ssa = _ssa_new("cond")
            ops.append({"id": ssa, "op": "COND.eval", "deps": deps, "args": {"expr": expr, "kind": kind}})
            return ssa

        def _emit_assign_from_ifexp(var_name: str, node: ast.IfExp) -> str:
            """Emit operations for an inline ``a if cond else b`` expression."""
            cond_id = _emit_cond(node.test, kind="ifexp")

            then_start = len(ops)
            then_id = _emit_value(f"{var_name}_then", node.body)
            if len(ops) > then_start:
                first = ops[then_start]
                deps0 = first.get("deps", []) or []
                if cond_id not in deps0:
                    first["deps"] = [*deps0, cond_id]

            else_start = len(ops)
            else_id = _emit_value(f"{var_name}_else", node.orelse)
            if len(ops) > else_start:
                first = ops[else_start]
                deps0 = first.get("deps", []) or []
                if cond_id not in deps0:
                    first["deps"] = [*deps0, cond_id]

            ssa = _ssa_new(var_name)
            ops.append({"id": ssa, "op": "PHI", "deps": [then_id, else_id], "args": {"var": var_name}})
            return ssa

        def _emit_assign_from_expr(var_name: str, node: ast.AST) -> str:
            """Emit a generic expression evaluation node for supported AST expressions."""

            deps = [_ssa_get(name) for name in _collect_value_deps(node)]
            expr = _stringify(node)
            ssa = _ssa_new(var_name)
            ops.append({
                "id": ssa,
                "op": "EXPR.eval",
                "deps": deps,
                "args": {"expr": expr},
            })
            return ssa

        def _emit_value(var_name: str, value: ast.AST) -> str:
            awaited = False
            if isinstance(value, ast.Await):
                value = value.value
                awaited = True
            if isinstance(value, ast.Call):
                return _emit_assign_from_call(var_name, value, awaited)
            if isinstance(value, ast.JoinedStr):
                return _emit_assign_from_fstring(var_name, value)
            if isinstance(value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
                return _emit_assign_from_literal_or_pack(var_name, value)
            if isinstance(value, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return _emit_assign_from_comp(var_name, value)
            if isinstance(value, ast.Subscript):
                return _emit_assign_from_subscript(var_name, value)
            if isinstance(value, ast.IfExp):
                return _emit_assign_from_ifexp(var_name, value)
            if isinstance(value, ast.Name):
                return _ssa_get(value.id)
            if isinstance(value, (ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare)):
                return _emit_assign_from_expr(var_name, value)
            expr = _stringify(value)
            raise DSLParseError(f"Unsupported right hand side expression: {expr}")

        def _emit_iter(node: ast.AST, target_label: Optional[str] = None) -> str:
            expr = _stringify(node)
            deps = [_ssa_get(n) for n in _collect_value_deps(node)]
            ssa = _ssa_new("iter")
            args = {"expr": expr, "kind": "for"}
            if target_label:
                args["target"] = target_label
            ops.append({"id": ssa, "op": "ITER.eval", "deps": deps, "args": args})
            return ssa

        def _parse_stmt(stmt: ast.stmt) -> Optional[str]:
            nonlocal returned_var, versions, latest, context_suffix, loop_depth
            if isinstance(stmt, ast.Assign):
                if len(stmt.targets) != 1:
                    raise DSLParseError("Assignment must have exactly one target")
                target = stmt.targets[0]
                if isinstance(target, ast.Name):
                    var_name = target.id
                    return _emit_value(var_name, stmt.value)
                elif isinstance(target, ast.Subscript):
                    return _emit_assign_to_subscript(target, stmt.value)
                else:
                    raise DSLParseError("Assignment targets must be simple names")
            elif isinstance(stmt, ast.Expr):
                call = stmt.value
                awaited = False
                if isinstance(call, ast.Await):
                    call = call.value
                    awaited = True
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
                    ssa_from = _ssa_get(var)
                    filename = None
                    for kw in call.keywords:
                        if kw.arg in {"as", "as_"}:
                            filename = _literal(kw.value)
                        else:
                            raise DSLParseError("output only accepts 'as' keyword")
                    if filename is None or not isinstance(filename, str):
                        raise DSLParseError("output requires as=\"filename\"")
                    outputs.append({"from": ssa_from, "as": filename})
                else:
                    # General expression call: represent as an op node too
                    _emit_expr_call(call, awaited)
                return None
            elif isinstance(stmt, ast.Return):
                if loop_depth > 0:
                    ssa = _ssa_new("break")
                    ops.append({"id": ssa, "op": "CTRL.break", "deps": [], "args": {}})
                if isinstance(stmt.value, ast.Name):
                    name = stmt.value.id
                    if name in latest:
                        returned_var = _ssa_get(name)
                    else:
                        const_id = _ssa_new("return_value")
                        ops.append({
                            "id": const_id,
                            "op": "CONST.value",
                            "deps": [],
                            "args": {"value": None},
                        })
                        returned_var = const_id
                elif isinstance(stmt.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
                    try:
                        lit = _literal(stmt.value)
                    except DSLParseError:
                        returned_var = _emit_assign_from_literal_or_pack("return_value", stmt.value)
                    else:
                        const_id = _ssa_new("return_value")
                        ops.append({
                            "id": const_id,
                            "op": "CONST.value",
                            "deps": [],
                            "args": {"value": lit},
                        })
                        returned_var = const_id
                else:
                    raise DSLParseError("return must return a variable name or literal")
                return None
            elif isinstance(stmt, ast.If):
                # Evaluate condition
                cond_id = _emit_cond(stmt.test, kind="if")
                # Save pre-branch state
                pre_versions = dict(versions)
                pre_latest = dict(latest)

                # THEN branch
                then_ops_start = len(ops)
                versions_then = dict(pre_versions)
                latest_then = dict(pre_latest)
                # Run then body with local state and context
                saved_versions, saved_latest = versions, latest
                saved_ctx = context_suffix
                ctx_counts["if"] += 1
                context_suffix = f"then{ctx_counts['if']}"
                versions, latest = versions_then, latest_then
                for inner in stmt.body:
                    _parse_stmt(inner)
                versions_then, latest_then = versions, latest
                versions, latest = saved_versions, saved_latest
                context_suffix = saved_ctx

                # ELSE branch
                else_ops_start = len(ops)
                versions_else = dict(pre_versions)
                latest_else = dict(pre_latest)
                saved_versions, saved_latest = versions, latest
                saved_ctx = context_suffix
                context_suffix = f"else{ctx_counts['if']}"
                versions, latest = versions_else, latest_else
                for inner in stmt.orelse or []:
                    _parse_stmt(inner)
                versions_else, latest_else = versions, latest
                versions, latest = saved_versions, saved_latest
                context_suffix = saved_ctx

                # Add cond dep to first op in each branch, if any
                if len(ops) > then_ops_start:
                    ops[then_ops_start]["deps"] = [*ops[then_ops_start].get("deps", []), cond_id]
                if len(ops) > else_ops_start:
                    ops[else_ops_start]["deps"] = [*ops[else_ops_start].get("deps", []), cond_id]

                # Determine variables assigned in branches
                then_assigned = {k for k in latest_then if pre_latest.get(k) != latest_then.get(k)}
                else_assigned = {k for k in latest_else if pre_latest.get(k) != latest_else.get(k)}
                all_assigned = then_assigned | else_assigned
                for var in sorted(all_assigned):
                    left = latest_then.get(var, pre_latest.get(var))
                    right = latest_else.get(var, pre_latest.get(var))
                    if left is None or right is None:
                        # Variable does not exist pre-branch on one side; skip making it available post-merge
                        continue
                    phi_id = _ssa_new(var)
                    ops.append({"id": phi_id, "op": "PHI", "deps": [left, right], "args": {"var": var}})
                return None
            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                # ITER over iterable
                # Determine loop target label if simple
                t = stmt.target
                t_label: Optional[str] = None
                if isinstance(t, ast.Name):
                    t_label = t.id
                elif isinstance(t, ast.Tuple) and all(isinstance(e, ast.Name) for e in t.elts):
                    t_label = ",".join(e.id for e in t.elts)  # type: ignore[attr-defined]
                else:
                    try:
                        t_label = ast.unparse(t)  # type: ignore[attr-defined]
                    except Exception:
                        t_label = None
                iter_id = _emit_iter(stmt.iter, target_label=t_label)
                # Save pre-loop state
                pre_versions = dict(versions)
                pre_latest = dict(latest)
                # Body state copy
                body_ops_start = len(ops)
                versions_body = dict(pre_versions)
                latest_body = dict(pre_latest)
                saved_versions, saved_latest = versions, latest
                saved_ctx = context_suffix
                ctx_counts["loop"] += 1
                context_suffix = f"loop{ctx_counts['loop']}"
                loop_depth += 1
                versions, latest = versions_body, latest_body
                # Predefine loop target variables as items from iterator for dependency resolution
                def _bind_loop_target(target: ast.AST):
                    if isinstance(target, ast.Name):
                        ssa_item = _ssa_new(target.id)
                        ops.append({
                            "id": ssa_item,
                            "op": "ITER.item",
                            "deps": [iter_id],
                            "args": {"target": target.id},
                        })
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                ssa_item = _ssa_new(elt.id)
                                ops.append({
                                    "id": ssa_item,
                                    "op": "ITER.item",
                                    "deps": [iter_id],
                                    "args": {"target": elt.id},
                                })
                    # Other patterns are ignored for now

                _bind_loop_target(stmt.target)
                for inner in stmt.body:
                    _parse_stmt(inner)
                loop_depth -= 1
                versions_body, latest_body = versions, latest
                versions, latest = saved_versions, saved_latest
                context_suffix = saved_ctx
                # Add iter dep to first op in body if not already present
                if len(ops) > body_ops_start:
                    first = ops[body_ops_start]
                    deps0 = first.get("deps", []) or []
                    if iter_id not in deps0:
                        first["deps"] = [*deps0, iter_id]
                # Emit a summary foreach comp node depending on iterable value deps
                iter_name_deps = _collect_value_deps(stmt.iter)
                foreach_deps = [_ssa_get(n) for n in iter_name_deps]
                ssa_foreach = _ssa_new("foreach")
                ops.append({
                    "id": ssa_foreach,
                    "op": "COMP.foreach",
                    "deps": foreach_deps,
                    "args": {"target": t_label or ""},
                })
                # Loop-carried vars: only those existing pre-loop and reassigned in body
                changed = {k for k in latest_body if pre_latest.get(k) != latest_body.get(k)}
                carried = [k for k in changed if k in pre_latest]
                for var in sorted(carried):
                    phi_id = _ssa_new(var)
                    ops.append({
                        "id": phi_id,
                        "op": "PHI",
                        "deps": [pre_latest[var], latest_body[var]],
                        "args": {"var": var},
                    })
                return None
            elif isinstance(stmt, ast.While):
                cond_id = _emit_cond(stmt.test, kind="while")
                pre_versions = dict(versions)
                pre_latest = dict(latest)
                body_ops_start = len(ops)
                versions_body = dict(pre_versions)
                latest_body = dict(pre_latest)
                saved_versions, saved_latest = versions, latest
                saved_ctx = context_suffix
                ctx_counts["while"] += 1
                context_suffix = f"while{ctx_counts['while']}"
                loop_depth += 1
                versions, latest = versions_body, latest_body
                for inner in stmt.body:
                    _parse_stmt(inner)
                loop_depth -= 1
                versions_body, latest_body = versions, latest
                versions, latest = saved_versions, saved_latest
                context_suffix = saved_ctx
                if len(ops) > body_ops_start:
                    first = ops[body_ops_start]
                    deps0 = first.get("deps", []) or []
                    if cond_id not in deps0:
                        first["deps"] = [*deps0, cond_id]
                changed = {k for k in latest_body if pre_latest.get(k) != latest_body.get(k)}
                carried = [k for k in changed if k in pre_latest]
                for var in sorted(carried):
                    phi_id = _ssa_new(var)
                    ops.append({
                        "id": phi_id,
                        "op": "PHI",
                        "deps": [pre_latest[var], latest_body[var]],
                        "args": {"var": var},
                    })
                return None
            elif isinstance(stmt, ast.Try):
                pre_versions = dict(versions)
                pre_latest = dict(latest)
                for inner in stmt.body:
                    _parse_stmt(inner)
                # else block executes only if no exception
                for inner in getattr(stmt, "orelse", []):
                    _parse_stmt(inner)
                post_versions = versions
                post_latest = latest
                for handler in getattr(stmt, "handlers", []):
                    saved_ctx = context_suffix
                    ctx_counts["except"] = ctx_counts.get("except", 0) + 1
                    context_suffix = f"except{ctx_counts['except']}"
                    saved_versions, saved_latest = versions, latest
                    versions, latest = dict(pre_versions), dict(pre_latest)
                    for inner in handler.body:
                        _parse_stmt(inner)
                    versions, latest = post_versions, post_latest
                    context_suffix = saved_ctx
                for inner in getattr(stmt, "finalbody", []):
                    _parse_stmt(inner)
                return None
            elif isinstance(stmt, ast.Break):
                ssa = _ssa_new("break")
                ops.append({"id": ssa, "op": "CTRL.break", "deps": [], "args": {}})
                return None
            elif isinstance(stmt, (ast.Pass, ast.Continue)):
                return None
            else:
                raise DSLParseError("Only assignments, control flow, settings/output calls, and return are allowed in function body")

        # Parse body sequentially; still require a resulting output
        body = list(getattr(fn, "body", []))  # type: ignore[attr-defined]
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(getattr(body[0].value, "value", None), str):  # type: ignore[attr-defined]
            body = body[1:]
        for stmt in body:
            _parse_stmt(stmt)

        # If no explicit return was encountered, emit a terminal break node so
        # that the plan represents function completion.
        break_id: Optional[str] = None
        if returned_var is None:
            break_id = _ssa_new("break")
            ops.append({"id": break_id, "op": "CTRL.break", "deps": [], "args": {}})

        # If no outputs were produced, synthesise a default return of `None` so
        # that parsing succeeds for empty functions.
        if returned_var is None and not outputs:
            const_id = _ssa_new("return_value")
            ops.append({
                "id": const_id,
                "op": "CONST.value",
                "deps": [],
                "args": {"value": None},
            })
            returned_var = const_id

        if not outputs:
            outputs.append({"from": returned_var if returned_var is not None else break_id, "as": "return"})

        if len(ops) > 2000:
            raise DSLParseError("Too many operations")

        fn_name = getattr(fn, "name", None)  # type: ignore[attr-defined]
        plan: Dict[str, Any] = {"version": 2, "function": fn_name, "ops": ops, "outputs": outputs}
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
        last_err: Optional[DSLParseError] = None
        fn_count = 0
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_count += 1
                try:
                    return _parse_fn(node)
                except DSLParseError as e:
                    last_err = e
                    continue
        # If we got here, either there are no functions or none matched the DSL
        if last_err is not None:
            if fn_count == 1:
                raise last_err
            raise DSLParseError("No suitable function matched the DSL; specify --func to disambiguate") from last_err
        raise DSLParseError("No function definitions found in source")


def parse_file(filename: str, function_name: Optional[str] = None) -> Dict[str, Any]:
    with open(filename, "r", encoding="utf-8") as f:
        src = f.read()
    return parse(src, function_name=function_name)
