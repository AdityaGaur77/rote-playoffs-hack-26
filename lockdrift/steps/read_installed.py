#!/usr/bin/env python3
"""Read what is actually INSTALLED on this disk.

    read_installed.py <root>

Emits one row per installed package:

    ecosystem FS name FS version FS install_path FS ""

Contract (rote step): stdout is data, exit status is the failure signal.

The distinction this step exists to preserve: "no install tree here" is NOT
"the install tree agrees". It reports `observed: false` so the join can mark
those dependencies UNCHECKED rather than SYNCED. A Play that blurs those two is
the reason nobody trusts dependency tooling.
"""
import json
import os
import re
import sys

FS = chr(31)
RS = chr(30)
MAX_DEPTH = 6
SKIP_DIRS = {".git", "__pycache__", "target", "dist", "build", ".next", ".tox"}


def die(msg):
    print(f"read_installed: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def scrub(value):
    return str(value).replace(FS, " ").replace(RS, " ")


def find_trees(root):
    """Top-level node_modules and site-packages directories under root."""
    node, site = [], []
    root = os.path.abspath(root)
    for dirpath, dirnames, _files in os.walk(root):
        if dirpath[len(root):].count(os.sep) >= MAX_DEPTH:
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) == "node_modules":
            node.append(dirpath)
            dirnames[:] = []                 # never descend into nested installs
            continue
        if os.path.basename(dirpath) == "site-packages":
            site.append(dirpath)
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    return sorted(node), sorted(site)


def npm_installed(tree, root, rows, broken):
    """node_modules/<name>/package.json, including @scope/<name>."""
    try:
        entries = sorted(os.listdir(tree))
    except OSError as exc:
        broken.append(f"{os.path.relpath(tree, root)}: {exc}")
        return
    packages = []
    for entry in entries:
        if entry.startswith(".") or entry == ".bin":
            continue
        full = os.path.join(tree, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith("@"):
            try:
                packages += [os.path.join(full, sub) for sub in sorted(os.listdir(full))]
            except OSError as exc:
                broken.append(f"{entry}: {exc}")
            continue
        packages.append(full)

    for path in packages:
        manifest = os.path.join(path, "package.json")
        if not os.path.isfile(manifest):
            continue
        try:
            with open(manifest, encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            broken.append(f"{os.path.relpath(manifest, root)}: {exc}")
            continue
        name = doc.get("name") if isinstance(doc, dict) else None
        version = doc.get("version") if isinstance(doc, dict) else None
        if isinstance(name, str) and isinstance(version, str):
            rows.append(("npm", name, version, os.path.relpath(path, root), ""))


DIST_INFO = re.compile(r"^(?P<name>.+?)-(?P<version>\d[^-]*)\.dist-info$")


def python_installed(tree, root, rows, broken):
    """<name>-<version>.dist-info, with METADATA as the fallback reading."""
    try:
        entries = sorted(os.listdir(tree))
    except OSError as exc:
        broken.append(f"{os.path.relpath(tree, root)}: {exc}")
        return
    for entry in entries:
        if not entry.endswith(".dist-info"):
            continue
        match = DIST_INFO.match(entry)
        if match:
            name = match.group("name").replace("_", "-")
            rows.append(("pypi", name, match.group("version"),
                         os.path.relpath(os.path.join(tree, entry), root), ""))
            continue
        # Directory name did not carry a version; read the metadata instead of
        # guessing one.
        meta = os.path.join(tree, entry, "METADATA")
        name = version = None
        try:
            with open(meta, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if line.startswith("Name:") and name is None:
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("Version:") and version is None:
                        version = line.split(":", 1)[1].strip()
                    elif not line.strip():
                        break
        except OSError as exc:
            broken.append(f"{entry}: {exc}")
            continue
        if name and version:
            rows.append(("pypi", name, version,
                         os.path.relpath(os.path.join(tree, entry), root), ""))


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(root):
        die(f"root is not a directory: {root}")
    root = os.path.abspath(root)

    node_trees, site_trees = find_trees(root)
    rows, broken = [], []
    for tree in node_trees:
        npm_installed(tree, root, rows, broken)
    for tree in site_trees:
        python_installed(tree, root, rows, broken)

    seen, unique = set(), []
    for row in rows:
        key = (row[0], row[1].lower())
        if key not in seen:
            seen.add(key)
            unique.append(row)

    observed = bool(node_trees or site_trees)
    payload = {
        "ok": True,
        "source": "installed",
        # The load-bearing field. False means nobody looked, which downstream
        # must read as unknown -- never as agreement.
        "observed": observed,
        "trees": len(node_trees) + len(site_trees),
        "count": len(unique),
        "packed": RS.join(FS.join(scrub(c) for c in row) for row in unique),
    }
    if not observed:
        payload["warning"] = (
            f"no node_modules or site-packages under {os.path.basename(root) or root}: "
            f"the installed state was not observed, so nothing can be called in sync "
            f"with it")
    if broken:
        payload["unreadable"] = len(broken)
        payload["warning"] = "; ".join(broken[:5])
    emit(payload)


if __name__ == "__main__":
    main()
