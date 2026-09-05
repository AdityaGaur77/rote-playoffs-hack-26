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


def _sections(text):
    """{section: {key: str | [str]}} for the shapes a manifest uses.

    Section awareness is the whole point. Scanning the file for any
    `key = [...]` reports `authors`, `classifiers` and `packages` as
    dependencies -- a reader inventing rows, which is the same failure as one
    hiding them.
    """
    sections, current, key, buffer = {}, "", None, None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("#") else ""
        if not line:
            continue
        if buffer is not None:
            buffer.append(line)
            if "]" in line:
                joined = " ".join(buffer)
                sections.setdefault(current, {})[key] = re.findall(
                    r'["\']([^"\']*)["\']', joined.split("[", 1)[1])
                key, buffer = None, None
            continue
        if line.startswith("["):
            current = line.strip("[]").strip()
            sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().strip("\"'"), value.strip()
        if value.startswith("[") and "]" not in value:
            buffer = [value]
            continue
        if value.startswith("["):
            sections.setdefault(current, {})[key] = re.findall(
                r'["\']([^"\']*)["\']', value)
        else:
            sections.setdefault(current, {})[key] = value.strip("\"'")
        key = None
    return sections


def _poetry_version(value):
    if isinstance(value, list):
        return ""
    if value.startswith("{"):
        match = re.search(r'version\s*=\s*["\']([^"\']*)["\']', value)
        return match.group(1) if match else ""
    return value


def pyproject_declared(path, rel, rows, broken):
    """Only the tables that actually declare runtime dependencies.

    `[build-system] requires` is deliberately excluded: those install into the
    build environment, not yours, and reporting them as your dependencies would
    be answering a different question than the one asked.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            sections = _sections(handle.read())
    except OSError as exc:
        broken.append(f"{rel}: {exc}")
        return

    for entry in sections.get("project", {}).get("dependencies") or []:
        parsed = pep508(entry)
        if parsed:
            rows.append(("pypi", parsed[0], parsed[1], rel, "project"))

    for group, entries in (sections.get("project.optional-dependencies") or {}).items():
        for entry in entries if isinstance(entries, list) else []:
            parsed = pep508(entry)
            if parsed:
                rows.append(("pypi", parsed[0], parsed[1], rel, f"optional:{group}"))

    for name, spec in (sections.get("tool.poetry.dependencies") or {}).items():
        if name.lower() == "python":
            continue
        rows.append(("pypi", name, _poetry_version(spec), rel, "poetry"))


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
