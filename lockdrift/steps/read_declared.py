#!/usr/bin/env python3
"""Read what the manifests DECLARE — ranges, not pins.

    read_declared.py <root>

Emits one row per declared dependency:

    ecosystem FS name FS range FS manifest_path FS section

Contract (rote step):
  stdout is data (one JSON object), exit status is the failure signal.
  Expected absence -> {"ok": true, "warning": ...} exit 0.
  Hard fault       -> message on stderr, exit 2.

Standard library only, and deliberately no TOML parser: tomllib is 3.11+ and
the tomli backport is a dependency. The pyproject and lock readers are regex
readers, which is a real limitation and is stated in the Play description
rather than hidden.
"""
import json
import os
import re
import sys

FS = chr(31)
RS = chr(30)

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "target",
    "dist", "build", ".tox", ".mypy_cache", "site-packages", ".next",
    "vendor", ".pytest_cache", "htmlcov",
}
MAX_DEPTH = 6

NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies")


def die(msg):
    print(f"read_declared: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def scrub(value):
    return str(value).replace(FS, " ").replace(RS, " ")


def walk(root):
    """Manifest paths under root, breadth-limited and vendor-free."""
    found = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name == "package.json" or name == "pyproject.toml" \
                    or (name.startswith("requirements") and name.endswith(".txt")):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def npm_declared(path, rel, rows, broken):
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        # A manifest that will not parse is a visible unknown, never a silent
        # "nothing declared here".
        broken.append(f"{rel}: {exc}")
        return
    if not isinstance(doc, dict):
        broken.append(f"{rel}: not a JSON object")
        return
    for section in NPM_SECTIONS:
        block = doc.get(section)
        if not isinstance(block, dict):
            continue
        for name, spec in block.items():
            if isinstance(spec, str):
                rows.append(("npm", name, spec, rel, section))


PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def pep508(entry):
    """('numpy>=1.26', ...) -> ('numpy', '>=1.26'). None when unparseable."""
    entry = entry.split("#", 1)[0].strip().strip(",").strip()
    entry = entry.strip('"').strip("'").strip()
    if not entry or entry.startswith("-"):
        return None
    if "@" in entry and "://" in entry:          # PEP 508 direct reference
        name = entry.split("@", 1)[0].strip()
        return (name, entry.split("@", 1)[1].strip()) if name else None
    m = PEP508.match(entry)
    if not m:
        return None
    name, _extras, rest = m.groups()
    rest = rest.split(";", 1)[0].strip()         # drop environment markers
    return name, rest


def pyproject_declared(path, rel, rows, broken):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        broken.append(f"{rel}: {exc}")
        return
    # [project] dependencies = [...] and [project.optional-dependencies]
    for match in re.finditer(
            r"^\s*(?:dependencies|[A-Za-z0-9_-]+)\s*=\s*\[(.*?)\]",
            text, re.S | re.M):
        block = match.group(1)
        # Only take blocks that look like requirement lists.
        for raw in re.findall(r'["\']([^"\']+)["\']', block):
            parsed = pep508(raw)
            if parsed and re.match(r"^[A-Za-z0-9]", parsed[0]):
                rows.append(("pypi", parsed[0], parsed[1], rel, "project"))


def requirements_declared(path, rel, rows, broken):
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        broken.append(f"{rel}: {exc}")
        return
    for line in lines:
        parsed = pep508(line)
        if parsed:
            rows.append(("pypi", parsed[0], parsed[1], rel, "requirements"))


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(root):
        die(f"root is not a directory: {root}")

    manifests = walk(root)
    rows, broken = [], []
    for path in manifests:
        rel = os.path.relpath(path, os.path.abspath(root))
        base = os.path.basename(path)
        if base == "package.json":
            npm_declared(path, rel, rows, broken)
        elif base == "pyproject.toml":
            pyproject_declared(path, rel, rows, broken)
        else:
            requirements_declared(path, rel, rows, broken)

    # Deduplicate on (ecosystem, name), keeping the first declaration seen.
    seen, unique = set(), []
    for row in rows:
        key = (row[0], row[1].lower())
        if key not in seen:
            seen.add(key)
            unique.append(row)

    payload = {
        "ok": True,
        "source": "declared",
        "count": len(unique),
        "manifests": ",".join(sorted({os.path.basename(p) for p in manifests})),
        "packed": RS.join(FS.join(scrub(c) for c in row) for row in unique),
    }
    if not manifests:
        payload["warning"] = f"no supported manifest found under {root}"
    elif not unique:
        payload["warning"] = f"{len(manifests)} manifest(s) found, none declaring dependencies"
    if broken:
        payload["unreadable"] = len(broken)
        payload["warning"] = "; ".join(broken[:5])
    emit(payload)


if __name__ == "__main__":
    main()
