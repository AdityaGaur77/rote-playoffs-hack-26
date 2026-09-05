#!/usr/bin/env python3
"""Read what the LOCKFILES pin.

    read_locked.py <root>

Emits one row per locked dependency:

    ecosystem FS name FS version FS lock_path FS scope

Contract (rote step): stdout is data, exit status is the failure signal.
An unparseable lockfile is a visible unknown -- it is reported, and the
dependencies it would have covered stay unknown downstream rather than
silently reading as "in sync".
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
LOCKS = ("package-lock.json", "npm-shrinkwrap.json", "uv.lock", "poetry.lock")


def die(msg):
    print(f"read_locked: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def scrub(value):
    return str(value).replace(FS, " ").replace(RS, " ")


def walk(root):
    found = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath[len(root):].count(os.sep) >= MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name in LOCKS:
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def npm_locked(path, rel, rows, broken):
    """package-lock v1 keys by name; v2/v3 key by node_modules path."""
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        broken.append(f"{rel}: {exc}")
        return
    if not isinstance(doc, dict):
        broken.append(f"{rel}: not a JSON object")
        return

    packages = doc.get("packages")
    if isinstance(packages, dict):                       # lockfileVersion 2/3
        for key, entry in packages.items():
            if not key or not isinstance(entry, dict):
                continue                                 # "" is the root project
            # Only hoisted top-level installs: one node_modules segment.
            if key.count("node_modules/") != 1 or not key.startswith("node_modules/"):
                continue
            name = key[len("node_modules/"):]
            version = entry.get("version")
            if isinstance(version, str):
                scope = "dev" if entry.get("dev") else "prod"
                rows.append(("npm", name, version, rel, scope))
        return

    deps = doc.get("dependencies")                       # lockfileVersion 1
    if isinstance(deps, dict):
        for name, entry in deps.items():
            if isinstance(entry, dict) and isinstance(entry.get("version"), str):
                scope = "dev" if entry.get("dev") else "prod"
                rows.append(("npm", name, entry["version"], rel, scope))
        return

    broken.append(f"{rel}: neither `packages` nor `dependencies` present")


# uv.lock and poetry.lock are TOML with [[package]] blocks. Read by regex on
# purpose: tomllib is 3.11+ and tomli is a dependency, and this Play declares
# a 3.8 floor with nothing to install.
PACKAGE_BLOCK = re.compile(r"^\s*\[\[package\]\]\s*$", re.M)
NAME_LINE = re.compile(r'^\s*name\s*=\s*["\']([^"\']+)["\']', re.M)
VERSION_LINE = re.compile(r'^\s*version\s*=\s*["\']([^"\']+)["\']', re.M)


def toml_locked(path, rel, rows, broken):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        broken.append(f"{rel}: {exc}")
        return
    starts = [m.start() for m in PACKAGE_BLOCK.finditer(text)]
    if not starts:
        broken.append(f"{rel}: no [[package]] blocks found")
        return
    bounds = starts + [len(text)]
    for i, start in enumerate(starts):
        block = text[start:bounds[i + 1]]
        name = NAME_LINE.search(block)
        version = VERSION_LINE.search(block)
        if name and version:
            rows.append(("pypi", name.group(1), version.group(1), rel, "prod"))


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(root):
        die(f"root is not a directory: {root}")

    locks = walk(root)
    rows, broken = [], []
    for path in locks:
        rel = os.path.relpath(path, os.path.abspath(root))
        if os.path.basename(path).endswith(".json"):
            npm_locked(path, rel, rows, broken)
        else:
            toml_locked(path, rel, rows, broken)

    seen, unique = set(), []
    for row in rows:
        key = (row[0], row[1].lower())
        if key not in seen:
            seen.add(key)
            unique.append(row)

    payload = {
        "ok": True,
        "source": "locked",
        "count": len(unique),
        "lockfiles": ",".join(sorted({os.path.basename(p) for p in locks})),
        "packed": RS.join(FS.join(scrub(c) for c in row) for row in unique),
    }
    if not locks:
        # This is the finding, not an error: nothing pins anything here.
        payload["warning"] = f"no lockfile found under {root}"
    if broken:
        payload["unreadable"] = len(broken)
        payload["warning"] = "; ".join(broken[:5])
    emit(payload)


if __name__ == "__main__":
    main()
