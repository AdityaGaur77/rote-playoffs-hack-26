#!/usr/bin/env python3
"""Step 4 — does this project actually import the package, and where?

This is the step that separates the Play from Dependabot. A breaking change in
a dependency you never import directly is not your problem; the same change in
one you call on line 42 is.

Contract (rote step):
  Never a hard fault for "not found" — a package with no call sites is a REAL
  ANSWER, not an absence. Only a bad invocation or unreadable root exits 2.

Standard library only. Walks the tree once rather than shelling out, so no
ripgrep dependency lands in deps.toml.
"""
import json
import os
import re
import sys

FS = chr(31)
RS = chr(30)

MAX_BYTES = 1_500_000        # skip anything bigger; it is not hand-written source
MAX_HITS = 40

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "target", "dist",
    "build", ".tox", ".mypy_cache", "site-packages", ".next", "vendor",
    "coverage", ".pytest_cache", ".ruff_cache", "htmlcov",
}

EXTS = {
    "npm":    {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".svelte", ".vue"},
    "pypi":   {".py", ".pyi"},
    "crates": {".rs"},
}


def die(msg):
    print(f"find_callsites: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def import_aliases(eco, name):
    """Plausible module names for a distribution name.

    Distribution name and import name often differ (PyPI beautifulsoup4 imports
    as bs4). We cannot resolve that from the registry alone, so we try the
    mechanical transforms and report honestly when nothing matches.
    """
    base = name.strip()
    out = {base}
    if eco == "pypi":
        out.add(base.replace("-", "_"))
        out.add(base.replace("-", ""))
        out.add(base.replace("_", "-"))
        if base.lower().startswith("python-"):
            out.add(base[7:].replace("-", "_"))
    elif eco == "crates":
        out.add(base.replace("-", "_"))
    elif eco == "npm":
        out.add(base)                       # scoped names like @scope/pkg stay whole
    return {a for a in out if a}


def patterns_for(eco, aliases):
    pats = []
    for alias in aliases:
        q = re.escape(alias)
        if eco == "npm":
            pats.append(re.compile(
                rf"""(?:require\s*\(\s*['"]{q}(?:/[^'"]*)?['"]\s*\)"""
                rf"""|from\s+['"]{q}(?:/[^'"]*)?['"]"""
                rf"""|import\s*\(\s*['"]{q}(?:/[^'"]*)?['"]\s*\))"""))
        elif eco == "pypi":
            # [ \t]* not \s* — under re.M, \s matches newlines, so the match would
            # start on an earlier blank line and report the wrong line number.
            pats.append(re.compile(
                rf"^[ \t]*(?:from\s+{q}(?:\.\w+)*\s+import\s+|import\s+{q}(?:\.\w+)*)",
                re.M))
        elif eco == "crates":
            pats.append(re.compile(
                rf"(?:^[ \t]*use\s+{q}\s*(?:::|;)|^[ \t]*extern\s+crate\s+{q}\b)", re.M))
    return pats


COMMENT_PREFIXES = ("//", "*", "/*", "#")


def is_commented(line):
    """True when the matched line is a whole-line comment.

    The Python and Rust patterns anchor with ^[ \\t]* so a leading # or // already
    prevents a match. The npm pattern cannot anchor — require() legitimately
    appears mid-line — so a commented-out require would otherwise be reported as
    a live call site and inflate the count this Play exists to shrink.
    """
    return line.lstrip().startswith(COMMENT_PREFIXES)


# ---------------------------------------------------------------------------
# Carrier record — how dependency facts cross a step boundary.
#
# Each stage fills its own columns and passes the rest through, so the whole
# triage runs as a linear DAG wired by value edges. No stage needs a file on
# disk, and no stage needs to know how many dependencies there are.
#
#   0 ecosystem   3 latest   6 outdated   9  first_site  12 markers
#   1 name        4 repo     7 direct     10 checked
#   2 current     5 gap      8 files      11 breaking
#
# Booleans are "1" / "0" when known and "" when the stage that fills them has
# not run. That third state is load-bearing: an unfilled column must read as
# UNKNOWN downstream, never as a clean bill of health.
# ---------------------------------------------------------------------------
COLS = 13


def scrub(value):
    """Field text can never contain the delimiters that frame it."""
    return str(value).replace(FS, " ").replace(RS, " ")


def unpack(packed):
    """Carrier rows, padded to COLS. Short rows come from an earlier stage."""
    rows = []
    for chunk in (packed or "").split(RS):
        if chunk:
            rows.append((chunk.split(FS) + [""] * COLS)[:COLS])
    return rows


def repack(rows):
    return RS.join(FS.join(scrub(col) for col in row) for row in rows)


def upstream_packed(arg):
    """The previous step's output, however the value edge chose to deliver it.

    A whole stdout payload (a JSON object) and a bare `packed` scalar are both
    accepted, so the step does not depend on whether the edge resolves
    `.stdout.text` or `.stdout.json.packed`.
    """
    text = (arg or "").strip()
    if not text.startswith("{"):
        return text
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        die(f"upstream payload will not parse as JSON: {exc}")
    if not isinstance(doc, dict):
        die("upstream payload is not a JSON object")
    return doc.get("packed", "")


def scan(root, eco, name):
    """Where, if anywhere, this project imports the package.

    "Not found" is a real answer, not an absence, so this never raises; only a
    bad invocation or an unreadable root is a hard fault, and that is checked
    once by the caller.
    """
    exts = EXTS.get(eco)
    base = {"ok": True, "ecosystem": eco, "name": name,
            "direct": False, "hits": 0, "files": 0, "packed": "", "scanned": 0}
    if not exts:
        base["warning"] = f"no source pattern for ecosystem: {eco}"
        return base

    aliases = import_aliases(eco, name)
    pats = patterns_for(eco, aliases)

    hits, files_with, scanned, unreadable = [], set(), 0, 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if os.path.splitext(fname)[1] not in exts:
                continue
            full = os.path.join(dirpath, fname)
            try:
                if os.path.getsize(full) > MAX_BYTES:
                    continue
                with open(full, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                unreadable += 1
                continue
            scanned += 1
            lines = text.splitlines()
            for pat in pats:
                for m in pat.finditer(text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    raw = lines[line_no - 1] if line_no <= len(lines) else ""
                    if is_commented(raw):
                        continue              # a commented-out import is not a call site
                    rel = os.path.relpath(full, root)
                    files_with.add(rel)
                    if len(hits) < MAX_HITS:
                        hits.append((rel, str(line_no), raw.strip()[:160]))
                    break                     # one live hit per pattern per file is enough

    base.update({
        "direct": bool(files_with),
        "hits": len(hits),
        "files": len(files_with),
        "scanned": scanned,
        "packed": RS.join(FS.join(h) for h in hits),
    })
    if not files_with:
        base["note"] = (f"{name} is not imported directly in {scanned} scanned "
                        f"source files — likely transitive")
    if unreadable:
        base["warning"] = f"{unreadable} file(s) could not be read"
    return base


def run_batch(root, arg):
    """Scan the tree once per dependency, filling carrier columns 7-9.

    first_site is the representative call site quoted in the final report; it
    is the reason a row reads "breaking, and you call it here" rather than
    "breaking, somewhere".
    """
    rows = unpack(upstream_packed(arg))
    if not rows:
        emit({"ok": True, "warning": "no dependencies on input", "count": 0,
              "direct": 0, "scanned": 0, "packed": ""})

    scanned = 0
    for row in rows:
        rec = scan(root, row[0], row[1])
        scanned = max(scanned, rec["scanned"])
        row[7] = "1" if rec["direct"] else "0"
        row[8] = str(rec["files"])
        first = rec["packed"].split(RS)[0] if rec["packed"] else ""
        if first:
            parts = first.split(FS)
            row[9] = f"{parts[0]}:{parts[1]}" if len(parts) > 1 else parts[0]

    emit({
        "ok": True,
        "count": len(rows),
        "direct": sum(1 for row in rows if row[7] == "1"),
        "scanned": scanned,
        "packed": repack(rows),
    })


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        if len(sys.argv) < 4:
            die("usage: find_callsites.py --batch <root> <upstream payload>")
        root = sys.argv[2]
        if not os.path.isdir(root):
            die(f"root is not a directory: {root}")
        run_batch(root, sys.argv[3])

    if len(sys.argv) < 4:
        die("usage: find_callsites.py <root> <ecosystem> <name>\n"
            "   or: find_callsites.py --batch <root> <upstream payload>")
    root, eco, name = sys.argv[1], sys.argv[2], sys.argv[3]
    if not os.path.isdir(root):
        die(f"root is not a directory: {root}")
    emit(scan(root, eco, name))


if __name__ == "__main__":
    main()
