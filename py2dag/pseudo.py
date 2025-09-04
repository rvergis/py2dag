import json
from typing import Dict, Any


def generate(plan: Dict[str, Any]) -> str:
    """Generate human readable pseudo-code from a plan dict."""
    lines = []
    settings = plan.get("settings")
    if settings:
        args = ", ".join(f"{k}={json.dumps(v)}" for k, v in settings.items())
        lines.append(f"settings({args})")
        lines.append("")
    for op in plan.get("ops", []):
        deps = op.get("deps", [])
        kw = op.get("args", {})
        parts = []
        if deps:
            parts.extend(deps)
        if kw:
            parts.extend(f"{k}={json.dumps(v)}" for k, v in kw.items())
        arg_str = ", ".join(parts)
        lines.append(f"{op['id']} = {op['op']}({arg_str})")
    if plan.get("ops"):
        lines.append("")
    for out in plan.get("outputs", []):
        lines.append(f"output({out['from']}, as={json.dumps(out['as'])})")
    return "\n".join(lines).rstrip() + "\n"

