#!/usr/bin/env python3
"""Step 3 — read release notes between two versions and judge them breaking.

Contract (rote step):
  Every remote problem is an EXPECTED ABSENCE -> ok:true, exit 0.

  The honesty rule that matters most here: when we cannot read the notes, the
  answer is "unknown", never "no breaking changes". A false negative here tells
  someone an upgrade is safe when nobody checked. `breaking` is only false when
  notes were actually read and contained no breaking markers; `checked` says
  which of those two situations you are in.

GITHUB_API_BASE overrides the API root (default https://api.github.com) for
GitHub Enterprise installs and for hermetic tests of the success path.

Rate limit: the GitHub REST API allows 60 unauthenticated requests per hour,
and a 47-dependency project blows through that. Set GITHUB_TOKEN to raise it to
5000/hr. The token is optional by design so the Play still runs with no
credentials at all -- it simply reports more "unknown" rows without one.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

FS = chr(31)
RS = chr(30)
UA = "upgrade-impact-triage/0.1 (+https://play.modiqo.ai)"
TIMEOUT = 25


def api_base():
    """Read at call time, not import time, so tests can point it at a stub."""
    return (os.environ.get("GITHUB_API_BASE", "").strip()
            or "https://api.github.com").rstrip("/")

BREAKING_PATTERNS = [
    (re.compile(r"\bBREAKING[ -]CHANGES?\b", re.I), "breaking-change"),
    (re.compile(r"^[ \t]*#{1,4}[ \t]*breaking\b", re.I | re.M), "breaking-heading"),
    (re.compile(r"\bbackwards?[- ]incompatible\b", re.I), "incompatible"),
    (re.compile(r"^[ \t]*[-*][ \t]*\*{0,2}(removed?|dropped?)\*{0,2}\s+", re.I | re.M), "removal"),
    (re.compile(r"\brenamed?\b.{0,40}\bto\b", re.I), "rename"),
    (re.compile(r"\bno longer\b", re.I), "no-longer"),
    (re.compile(r"\bmigration guide\b", re.I), "migration-guide"),
]


# GitHub's `prerelease` flag is author-set and often left false on rc tags,
# so the tag itself is the more reliable signal. Requires digits around the
# marker so "v1.2.3-abc" is not read as an alpha.
PRERELEASE_TAG = re.compile(
    r"\d(?:[-._]?(?:rc|alpha|beta|dev|pre)\d*|(?:a|b|rc)\d+)\b", re.I)


def is_prerelease(rel):
    return bool(rel.get("prerelease")
                or PRERELEASE_TAG.search(str(rel.get("tag_name") or "")))


def first_line(text, pos):
    """The first non-blank line at or after `pos`.

    A match can begin on a blank line, so the text at `pos` is not always the
    line worth quoting. Never return an empty sample.
    """
    for line in text[pos:pos + 400].splitlines():
        if line.strip():
            return line.strip()
    return ""


def die(msg):
    print(f"fetch_changelog: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def parse_version(v):
    parts = re.findall(r"\d+", str(v) or "")
    return tuple(int(p) for p in parts[:3]) + (0,) * (3 - len(parts[:3]))


def tag_version(tag):
    """Pull a version tuple out of a release tag such as v1.2.3 or rel-1.2.3."""
    m = re.search(r"(\d+(?:\.\d+){0,2})", str(tag) or "")
    return parse_version(m.group(1)) if m else None


def get_json(url):
    """Return (data, error, rate_limited)."""
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8")), "", False
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code in (403, 429) and remaining == "0":
            return None, "GitHub API rate limit reached (set GITHUB_TOKEN to raise it)", True
        if exc.code == 404:
            return None, "no releases published for this repository", False
        return None, f"HTTP {exc.code}", False
    except Exception as exc:                              # noqa: BLE001
        return None, str(exc), False


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


def read_notes(repo, current, latest):
    """Read the release notes between two versions and judge them breaking.

    Never raises: every remote problem is an expected absence. When the notes
    cannot be read the answer is `checked: false` — "unknown" — and never
    `breaking: false`.
    """
    base = {
        "ok": True, "repo": repo, "current": current, "latest": latest,
        "checked": False,          # were release notes actually read?
        "breaking": False,         # only meaningful when checked is true
        "releases": 0, "markers": "", "packed": "",
    }

    cur_v, new_v = parse_version(current), parse_version(latest)

    if not repo or "/" not in repo:
        base["warning"] = "no GitHub repository known; cannot read release notes"
        if new_v[0] > cur_v[0]:
            base["markers"] = "major-version-bump"
            base["note"] = "unread notes, but a major version bump implies breaking changes"
        return base

    data, err, limited = get_json(
        f"{api_base()}/repos/{urllib.parse.quote(repo)}/releases?per_page=100")
    if data is None:
        base["warning"] = f"{repo}: {err}"
        base["rate_limited"] = limited
        # Major bumps are breaking by semver convention even when notes are unreadable.
        if new_v[0] > cur_v[0]:
            base["markers"] = "major-version-bump"
            base["note"] = "unread notes, but a major version bump implies breaking changes"
        return base

    candidates = []
    for rel in data:
        if rel.get("draft"):
            continue
        tv = tag_version(rel.get("tag_name"))
        if tv is None or not (cur_v < tv <= new_v):
            continue
        candidates.append(rel)

    # A release candidate's notes are superseded by the final release's, so
    # counting both reports every finding twice (v2.4.0 and v2.4.0rc1 with
    # identical text). Drop prereleases -- unless they are all there is, in
    # which case they are the only evidence available and dropping them would
    # turn a real finding into a false "nothing to read".
    stable = [rel for rel in candidates if not is_prerelease(rel)]
    in_range = stable or candidates

    markers, samples = set(), []
    for rel in in_range:
        body = rel.get("body") or ""
        for pat, label in BREAKING_PATTERNS:
            m = pat.search(body)
            if m:
                markers.add(label)
                line = first_line(body, m.start())
                if line and len(samples) < 12:
                    samples.append((str(rel.get("tag_name") or "?"), label, line[:150]))

    base.update({
        "checked": True,
        "releases": len(in_range),
        "breaking": bool(markers),
        "markers": ",".join(sorted(markers)),
        "packed": RS.join(FS.join(s) for s in samples),
    })

    if not in_range:
        base["checked"] = False
        base["warning"] = (f"{repo}: no releases found between {current} and {latest} "
                           f"(project may use tags or a CHANGELOG file instead)")
        if new_v[0] > cur_v[0]:
            base["markers"] = "major-version-bump"
    elif new_v[0] > cur_v[0] and not markers:
        base["breaking"] = True
        base["markers"] = "major-version-bump"
        base["note"] = "no breaking wording in notes, but the major version changed"

    return base


def run_batch(arg):
    """Read notes for every outdated dependency, filling carrier columns 10-12.

    Dependencies already at the latest version are skipped: their columns stay
    empty, which downstream reads as CURRENT rather than as a verdict. Nothing
    here can turn an unread changelog into a clean one — a rate-limited run
    leaves `checked` at "0" and produces more REVIEW rows, never fewer ACT rows.
    """
    rows = unpack(upstream_packed(arg))
    if not rows:
        emit({"ok": True, "warning": "no dependencies on input", "count": 0,
              "checked": 0, "breaking": 0, "packed": ""})

    checked = breaking = limited = skipped = 0
    warnings = []
    for row in rows:
        if row[6] != "1":                     # not outdated; nothing to compare
            skipped += 1
            continue
        rec = read_notes(row[4], row[2], row[3])
        if rec.get("rate_limited"):
            limited += 1
        elif rec.get("warning"):
            warnings.append(rec["warning"])
        row[10] = "1" if rec["checked"] else "0"
        row[11] = "1" if rec["breaking"] else "0"
        row[12] = rec["markers"]
        checked += bool(rec["checked"])
        breaking += bool(rec["breaking"])

    payload = {
        "ok": True,
        "count": len(rows),
        "considered": len(rows) - skipped,
        "checked": checked,
        "breaking": breaking,
        "packed": repack(rows),
    }
    if limited:
        payload["rate_limited"] = limited
        payload["warning"] = (f"{limited} changelog(s) unread: GitHub API rate limit "
                              f"reached. Set GITHUB_TOKEN to raise it to 5000/hr; "
                              f"until then these report as REVIEW, not SAFE.")
    elif warnings:
        # "checked: 0" on its own says nothing about why. A 403, an unknown
        # repository and a project that tags instead of releasing all degrade to
        # REVIEW, and they are not the same problem to fix.
        payload["unread"] = len(warnings)
        payload["warning"] = "; ".join(warnings[:5])
    emit(payload)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            die("usage: fetch_changelog.py --batch <upstream payload>")
        run_batch(sys.argv[2])

    if len(sys.argv) < 4:
        die("usage: fetch_changelog.py <owner/repo> <current_version> <latest_version>\n"
            "   or: fetch_changelog.py --batch <upstream payload>")
    emit(read_notes(sys.argv[1], sys.argv[2], sys.argv[3]))


if __name__ == "__main__":
    main()
