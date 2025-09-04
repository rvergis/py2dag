import re
import sys
from pathlib import Path


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def read_version(text: str) -> str:
    m = re.search(r"(?m)^version\s*=\s*\"(\d+\.\d+\.\d+)\"", text)
    return m.group(1) if m else "0.0.0"


def bump_patch(version: str) -> str:
    major, minor, patch = map(int, version.split("."))
    patch += 1
    return f"{major}.{minor}.{patch}"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"print", "bump"}:
        print("Usage: python scripts/version_utils.py [print|bump]", file=sys.stderr)
        return 2

    text = PYPROJECT.read_text(encoding="utf-8")
    current = read_version(text)

    if argv[1] == "print":
        print(current)
        return 0

    # bump
    new_version = bump_patch(current)
    new_text = re.sub(
        r"(?m)^version\s*=\s*\"(\d+\.\d+\.\d+)\"",
        f'version = "{new_version}"',
        text,
        count=1,
    )
    PYPROJECT.write_text(new_text, encoding="utf-8")
    print("Bumped to:", new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
