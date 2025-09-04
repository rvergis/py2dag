from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from setuptools import find_packages, setup


def read_pyproject() -> Dict[str, Any]:
    pyproject = Path(__file__).parent / "pyproject.toml"
    data: Dict[str, Any]
    try:
        if sys.version_info >= (3, 11):
            import tomllib  # type: ignore

            with pyproject.open("rb") as f:
                data = tomllib.load(f)
        else:
            import tomli  # type: ignore

            with pyproject.open("rb") as f:
                data = tomli.load(f)
    except Exception:
        # Minimal fallback: parse just name/version/description with regex
        text = pyproject.read_text(encoding="utf-8")
        def grab(key: str, default: str = "") -> str:
            m = re.search(rf"^\s*{key}\s*=\s*\"([^\"]+)\"", text, flags=re.M)
            return m.group(1) if m else default
        tool_poetry = {
            "name": grab("name", "py2dag"),
            "version": grab("version", "0.0.0"),
            "description": grab("description", ""),
        }
        data = {"tool": {"poetry": tool_poetry}, "project": {}}
    return data


def poetry_to_setup_kwargs(data: Dict[str, Any]) -> Dict[str, Any]:
    meta = data.get("tool", {}).get("poetry", {})
    name = meta.get("name", "py2dag")
    version = meta.get("version", "0.0.0")
    description = meta.get("description", "")
    authors = meta.get("authors", [])
    license_ = meta.get("license")
    readme = Path("README.md").read_text(encoding="utf-8") if Path("README.md").exists() else ""

    # Dependencies (exclude python)
    deps = meta.get("dependencies", {})
    install_requires: List[str] = []
    for pkg, spec in deps.items():
        if pkg.lower() == "python":
            continue
        if isinstance(spec, str):
            install_requires.append(f"{pkg}{spec if spec != '*' else ''}")
        elif isinstance(spec, dict):
            ver = spec.get("version", "")
            if ver and ver != "*":
                install_requires.append(f"{pkg}{ver}")

    extras = meta.get("extras", {})
    entry_points = {}
    scripts = meta.get("scripts", {})
    if scripts:
        entry_points["console_scripts"] = [f"{k} = {v}" for k, v in scripts.items()]

    return {
        "name": name,
        "version": version,
        "description": description,
        "long_description": readme,
        "long_description_content_type": "text/markdown",
        "license": license_,
        "author": ", ".join(authors) if authors else None,
        "packages": find_packages(include=["py2dag", "py2dag.*"]),
        "include_package_data": True,
        "install_requires": install_requires,
        "extras_require": extras,
        "entry_points": entry_points,
        "python_requires": ">=3.8",
    }


if __name__ == "__main__":
    data = read_pyproject()
    kwargs = poetry_to_setup_kwargs(data)
    setup(**kwargs)

