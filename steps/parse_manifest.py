#!/usr/bin/env python3
"""Step 1 — find dependency manifests under a root and emit one flat dependency list.

Contract (rote step):
  stdout is data (one JSON object), exit status is the failure signal.
  Expected absence -> {"ok": true, "warning": ...} exit 0.
  Hard fault       -> message on stderr, exit 2.

Collections cross step boundaries as a delimited scalar, because value-edge jq
must resolve to a scalar. Records are RS-separated, fields FS-separated:
  ecosystem FS name FS current_spec
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
}


def die(msg):
    print(f"parse_manifest: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def clean_version(spec):
    """Strip range operators to a bare version. '^1.2.3' -> '1.2.3'."""
    if not isinstance(spec, str):
        return ""
    m = re.search(r"(\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.\-]+)?)", spec)
    return m.group(1) if m else ""


def from_package_json(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for field in ("dependencies", "devDependencies"):
        for name, spec in (data.get(field) or {}).items():
            # Skip non-registry specs: file:, link:, git+, workspace:, npm alias
            if isinstance(spec, str) and re.match(r"^(file:|link:|git|https?:|workspace:|npm:)", spec):
                continue
            out.append(("npm", name, clean_version(spec)))
    return out


# ---------------------------------------------------------------------------
# tomllib landed in Python 3.11. This Play declares a 3.8 floor and stock macOS
# ships 3.9.6, so on a very ordinary machine `import tomllib` fails. It used to
# fail by returning [] -- which read as "this manifest declares nothing" rather
# than "nobody could read this manifest", and a pyproject full of dependencies
# vanished under a green stage bar. That is the exact failure this Play exists
# to report, committed by the Play itself.
#
# So: tomllib when it is there, this reader when it is not, and a raise if
# neither can read the file, which the caller already turns into a warning.
# Deliberately small -- section headers, strings, inline tables and arrays of
# strings. Enough for a dependency table and nothing more.
# ---------------------------------------------------------------------------

def _strip_comment(line):
    out, quote = [], ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def _toml_sections(text):
    """{section name: {key: str | [str]}} for the shapes a manifest uses."""
    sections, current = {}, ""
    key, buffer = None, None
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        if buffer is not None:                       # inside a multi-line array
            buffer.append(line)
            if "]" in line:
                joined = " ".join(buffer)
                sections.setdefault(current, {})[key] = re.findall(
                    r'["\']([^"\']*)["\']', joined.split("[", 1)[1])
                key, buffer = None, None
            continue
        if line.startswith("[["):
            current = line.strip("[]").strip()
            sections.setdefault(current, {})
            continue
        if line.startswith("["):
            current = line.strip("[]").strip()
            sections.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().strip('"\''), value.strip()
        if value.startswith("[") and "]" not in value:
            buffer = [value]
            continue
        if value.startswith("["):
            sections.setdefault(current, {})[key] = re.findall(
                r'["\']([^"\']*)["\']', value)
        else:
            sections.setdefault(current, {})[key] = value.strip('"\'')
        if buffer is None:
            key = None
    return sections


def _inline_version(value):
    """'{ version = "1.2", features = [...] }' -> '1.2'; a bare string as-is."""
    if isinstance(value, list):
        return ""
    if value.startswith("{"):
        match = re.search(r'version\s*=\s*["\']([^"\']*)["\']', value)
        return match.group(1) if match else ""
    return value


def _read_toml(path):
    """The parsed document, or None when only the fallback reader is available."""
    try:
        import tomllib
    except ModuleNotFoundError:
        return None
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _pep508_into(entries, out):
    for entry in entries or []:
        if not isinstance(entry, str):
            continue
        name = re.split(r"[<>=!~\[; ]", entry.strip(), maxsplit=1)[0]
        if name:
            out.append(("pypi", name, clean_version(entry)))


def _table_into(table, out):
    for name, spec in (table or {}).items():
        if name.lower() == "python":
            continue
        if isinstance(spec, dict):
            spec = spec.get("version", "")
        if isinstance(spec, str):
            out.append(("pypi", name, clean_version(spec)))


def from_pyproject(path):
    """Every table a pyproject actually declares dependencies in.

    Reading only `[project] dependencies` misses the ones that bite hardest --
    test and dev groups are where a breaking change surfaces first, in CI, on
    someone else's machine.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    data = _read_toml(path)
    if data is None:
        return _pyproject_fallback(path, text)

    out = []
    project = data.get("project") or {}
    _pep508_into(project.get("dependencies"), out)
    for entries in (project.get("optional-dependencies") or {}).values():
        _pep508_into(entries, out)
    for entries in (data.get("dependency-groups") or {}).values():   # PEP 735
        _pep508_into(entries, out)

    tool = data.get("tool") or {}
    poetry = tool.get("poetry") or {}
    _table_into(poetry.get("dependencies"), out)
    for group in (poetry.get("group") or {}).values():
        _table_into((group or {}).get("dependencies"), out)
    for entries in ((tool.get("pdm") or {}).get("dev-dependencies") or {}).values():
        _pep508_into(entries, out)

    # The same guard the fallback carries. Without it the two paths disagree:
    # a table neither reader handles warned on 3.9 and passed silently on 3.11,
    # which is the original bug again, on the Python most people run.
    return _refuse_silent_empty(path, text, out)


def _refuse_silent_empty(path, text, found):
    """A reduced reader that finds nothing in a file that plainly declares
    dependencies has failed to read it, not read it successfully. Raising is
    what turns that into a warning instead of a second silent zero."""
    if found:
        return found
    if re.search(r"(?m)^\s*\[[^\]]*dependencies\s*\]", text) or \
            re.search(r"(?m)^\s*dependencies\s*=", text):
        raise ValueError(
            "declares a dependency table this Python cannot parse: tomllib "
            "needs 3.11+ and the fallback reader could not read it")
    return found


def _pyproject_fallback(path, text):
    """pyproject.toml without tomllib. Raises if it cannot read the file, so
    the caller records it as unreadable instead of as empty."""
    sections = _toml_sections(text)
    out = []
    for entry in sections.get("project", {}).get("dependencies") or []:
        name = re.split(r"[<>=!~\[; ]", entry.strip(), maxsplit=1)[0]
        if name:
            out.append(("pypi", name, clean_version(entry)))
    for group, entries in (sections.get("project.optional-dependencies") or {}).items():
        if isinstance(entries, list):
            _pep508_into(entries, out)
    for group, entries in (sections.get("dependency-groups") or {}).items():
        if isinstance(entries, list):
            _pep508_into(entries, out)
    for name, spec in (sections.get("tool.poetry.dependencies") or {}).items():
        if name.lower() == "python":
            continue
        out.append(("pypi", name, clean_version(_inline_version(spec))))
    for section, table in sections.items():
        if section.startswith("tool.poetry.group.") and section.endswith(".dependencies"):
            for name, spec in table.items():
                if name.lower() != "python":
                    out.append(("pypi", name, clean_version(_inline_version(spec))))
        elif section == "tool.pdm.dev-dependencies":
            for entries in table.values():
                if isinstance(entries, list):
                    _pep508_into(entries, out)
    return _refuse_silent_empty(path, text, out)


def _cargo_fallback(path):
    """Cargo.toml without tomllib. Same contract: read it or raise."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    sections = _toml_sections(text)
    out = []
    for field in ("dependencies", "dev-dependencies"):
        for name, spec in (sections.get(field) or {}).items():
            if isinstance(spec, str) and spec.startswith("{"):
                if re.search(r'\b(path|git)\s*=', spec):
                    continue
            out.append(("crates", name, clean_version(_inline_version(spec))))
    return _refuse_silent_empty(path, text, out)


def from_requirements(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
            if name:
                out.append(("pypi", name, clean_version(line)))
    return out


def from_cargo(path):
    data = _read_toml(path)
    if data is None:
        return _cargo_fallback(path)
    out = []
    for field in ("dependencies", "dev-dependencies"):
        for name, spec in (data.get(field) or {}).items():
            if isinstance(spec, dict):
                if "path" in spec or "git" in spec:
                    continue
                spec = spec.get("version", "")
            out.append(("crates", name, clean_version(spec)))
    return out


READERS = {
    "package.json": from_package_json,
    "pyproject.toml": from_pyproject,
    "requirements.txt": from_requirements,
    "Cargo.toml": from_cargo,
}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(root):
        die(f"root is not a directory: {root}")

    deps, seen, manifests, unreadable = [], set(), [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            reader = READERS.get(fname)
            if not reader:
                continue
            full = os.path.join(dirpath, fname)
            try:
                found = reader(full)
            except Exception as exc:                      # noqa: BLE001
                unreadable.append(f"{os.path.relpath(full, root)}: {exc}")
                continue
            manifests.append(os.path.relpath(full, root))
            for eco, name, ver in found:
                key = (eco, name.lower())
                if key in seen:
                    continue
                seen.add(key)
                deps.append((eco, name, ver))

    if not manifests:
        if unreadable:
            warning = "every manifest found failed to parse: " + "; ".join(unreadable)
        else:
            warning = f"no supported manifest found under {root}"
        emit({
            "ok": True, "warning": warning,
            "count": 0, "packed": "", "manifests": "", "ecosystems": "",
        })

    packed = RS.join(FS.join([e, n, v]) for e, n, v in deps)
    payload = {
        "ok": True,
        "count": len(deps),
        "packed": packed,
        "manifests": ",".join(sorted(manifests)),
        "ecosystems": ",".join(sorted({e for e, _, _ in deps})),
    }
    if unreadable:
        payload["warning"] = "; ".join(unreadable)
    emit(payload)


if __name__ == "__main__":
    main()
