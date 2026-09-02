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


def main():
    if len(sys.argv) < 4:
        die("usage: fetch_changelog.py <owner/repo> <current_version> <latest_version>")
    repo, current, latest = sys.argv[1], sys.argv[2], sys.argv[3]

    base = {
        "ok": True, "repo": repo, "current": current, "latest": latest,
        "checked": False,          # were release notes actually read?
        "breaking": False,         # only meaningful when checked is true
        "releases": 0, "markers": "", "packed": "",
    }

    if not repo or "/" not in repo:
        base["warning"] = "no GitHub repository known; cannot read release notes"
        emit(base)

    cur_v, new_v = parse_version(current), parse_version(latest)

    data, err, limited = get_json(
        f"{api_base()}/repos/{urllib.parse.quote(repo)}/releases?per_page=100")
    if data is None:
        base["warning"] = f"{repo}: {err}"
        base["rate_limited"] = limited
        # Major bumps are breaking by semver convention even when notes are unreadable.
        if new_v[0] > cur_v[0]:
            base["markers"] = "major-version-bump"
            base["note"] = "unread notes, but a major version bump implies breaking changes"
        emit(base)

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

    emit(base)


if __name__ == "__main__":
    main()
