#!/usr/bin/env python3
"""Step 2 — one dependency, one registry reading.

Runs once per dependency under `for_each`. Answers: what is the latest version,
how big is the gap, and where does its source live (so the changelog step can
find release notes).

Contract (rote step):
  Network trouble or an unknown package is an EXPECTED ABSENCE -> ok:true with a
  warning, exit 0, so one dead package cannot kill a 47-dependency report.
  Only a malformed invocation is a hard fault -> stderr, exit 2.

Uses only the standard library, so deps.toml declares python3 and nothing else.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

FS = chr(31)
RS = chr(30)
UA = "upgrade-impact-triage/0.1 (+https://play.modiqo.ai)"
TIMEOUT = 20


def die(msg):
    print(f"fetch_registry: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def get_json(url, attempts=3):
    """GET JSON with a User-Agent. crates.io answers 403 without one."""
    last = ""
    for i in range(attempts):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8")), ""
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, "not found in registry"
            last = f"HTTP {exc.code}"
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (i + 1))
                continue
            return None, last
        except Exception as exc:                          # noqa: BLE001
            last = str(exc)
            time.sleep(1.0 * (i + 1))
    return None, last or "unreachable"


def parse_version(v):
    parts = re.findall(r"\d+", v or "")
    return [int(p) for p in parts[:3]] + [0] * (3 - len(parts[:3]))


def is_prerelease(v):
    return bool(re.search(r"[-+](alpha|beta|rc|dev|pre|a\d|b\d)", str(v), re.I))


def gap_between(cur, new):
    if not cur or not new:
        return "unknown"
    c, n = parse_version(cur), parse_version(new)
    if n == c:
        return "none"
    if n < c:
        return "ahead"
    if n[0] != c[0]:
        return "major"
    if n[1] != c[1]:
        return "minor"
    return "patch"


def norm_repo(url):
    """Normalise a repository field to owner/name on GitHub, else ''.

    Anchors on the FIRST two path segments after the host: a tracker URL such as
    github.com/numpy/numpy/issues must resolve to numpy/numpy, never numpy/issues.
    """
    if not isinstance(url, str):
        return ""
    m = re.search(
        r"github\.com[:/]+([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?(?:[/#?]|$)",
        url.strip(),
    )
    if not m:
        return ""
    owner, name = m.group(1), m.group(2)
    if owner.lower() in ("sponsors", "orgs", "apps", "settings"):
        return ""
    return f"{owner}/{name}"


def repo_from_urls(project_urls, *fallbacks):
    """Find a source repo among PyPI project_urls.

    Keys are author-supplied and their case varies ('source' for numpy,
    'Source Code' for others), so match case-insensitively on a priority list
    before scanning every value for any GitHub URL.
    """
    urls = {str(k).strip().lower(): v for k, v in (project_urls or {}).items()}
    for key in ("source", "source code", "repository", "code", "github", "homepage", "home"):
        found = norm_repo(urls.get(key))
        if found:
            return found
    for value in urls.values():                 # any GitHub URL beats nothing
        found = norm_repo(value)
        if found:
            return found
    for value in fallbacks:
        found = norm_repo(value)
        if found:
            return found
    return ""


def npm(name):
    data, err = get_json(f"https://registry.npmjs.org/{urllib.request.quote(name, safe='@')}")
    if data is None:
        return None, err
    latest = ((data.get("dist-tags") or {}).get("latest")) or ""
    repo = (data.get("repository") or {})
    repo_url = repo.get("url") if isinstance(repo, dict) else repo
    return {"latest": latest, "repo": norm_repo(repo_url)}, ""


def pypi(name):
    data, err = get_json(f"https://pypi.org/pypi/{urllib.request.quote(name)}/json")
    if data is None:
        return None, err
    info = data.get("info") or {}
    repo = repo_from_urls(info.get("project_urls"), info.get("home_page"))
    return {"latest": info.get("version") or "", "repo": repo}, ""


def crates(name):
    data, err = get_json(f"https://crates.io/api/v1/crates/{urllib.request.quote(name)}")
    if data is None:
        return None, err
    crate = data.get("crate") or {}
    repo = norm_repo(crate.get("repository"))
    return {"latest": crate.get("max_stable_version") or crate.get("newest_version") or "",
            "repo": repo}, ""


FETCHERS = {"npm": npm, "pypi": pypi, "crates": crates}


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
        # rote cuts a step's stdout at 64 KiB and still records the step as
        # completed, so a payload that opens like JSON and does not close like
        # it was almost certainly truncated in transport rather than malformed
        # at the source. Naming that beats a parser complaint about an escape
        # sequence 65,000 characters in.
        if not text.endswith("}"):
            # Only blame the cap when the size supports it. A short unclosed
            # payload ends mid-value too, and calling that a 64 KiB truncation
            # would be asserting a cause the evidence does not carry.
            hint = (" rote caps a step's stdout at 65,536 bytes and still reports the "
                    "step completed, so this is almost certainly that cut."
                    if len(text) >= 60_000 else "")
            die(f"upstream payload ends mid-value at {len(text):,} bytes, so the "
                f"dependencies past the cut were never seen.{hint} Failing closed "
                f"rather than triaging a partial list.")
        die(f"upstream payload will not parse as JSON: {exc}")
    if not isinstance(doc, dict):
        die("upstream payload is not a JSON object")
    return doc.get("packed", "")


def resolve(eco, name, current):
    """One dependency, one registry reading.

    Never raises: a remote problem is an expected absence carried in the
    payload, so one dead package cannot kill a 47-dependency report.
    """
    fetcher = FETCHERS.get(eco)
    base = {"ok": True, "ecosystem": eco, "name": name, "current": current,
            "latest": "", "repo": "", "gap": "unknown", "outdated": False}

    if not fetcher:
        base["warning"] = f"unsupported ecosystem: {eco}"
        return base

    facts, err = fetcher(name)
    if facts is None:
        base["warning"] = f"{name}: {err}"
        return base

    latest = facts["latest"]
    gap = gap_between(current, latest)
    base.update({
        "latest": latest,
        "repo": facts["repo"],
        "gap": gap,
        "outdated": gap in ("major", "minor", "patch"),
        "prerelease": is_prerelease(latest),
    })
    if not facts["repo"]:
        base["warning"] = f"{name}: no GitHub source URL published; changelog unavailable"
    return base


def run_batch(arg):
    """Resolve every dependency the manifest step found, in one step.

    Fills carrier columns 2-6 (current, latest, repo, gap, outdated) and leaves
    everything else for the stages downstream.
    """
    rows = unpack(upstream_packed(arg))
    if not rows:
        emit({"ok": True, "warning": "no dependencies on input", "count": 0,
              "resolved": 0, "outdated": 0, "packed": ""})

    warnings = []
    for row in rows:
        rec = resolve(row[0], row[1], row[2])
        if rec.get("warning"):
            warnings.append(rec["warning"])
        row[2] = rec["current"]
        row[3] = rec["latest"]
        row[4] = rec["repo"]
        row[5] = rec["gap"]
        row[6] = "1" if rec["outdated"] else "0"

    payload = {
        "ok": True,
        "count": len(rows),
        "resolved": len(rows) - len(warnings),
        "outdated": sum(1 for row in rows if row[6] == "1"),
        "packed": repack(rows),
    }
    if warnings:
        payload["unresolved"] = len(warnings)
        payload["warning"] = "; ".join(warnings[:5])
    emit(payload)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            die("usage: fetch_registry.py --batch <upstream payload>")
        run_batch(sys.argv[2])

    if len(sys.argv) < 3:
        die("usage: fetch_registry.py <ecosystem> <name> [current_version]\n"
            "   or: fetch_registry.py --batch <upstream payload>")
    emit(resolve(sys.argv[1], sys.argv[2],
                 sys.argv[3] if len(sys.argv) > 3 else ""))


if __name__ == "__main__":
    main()
