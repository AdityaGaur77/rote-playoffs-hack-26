#!/usr/bin/env python3
"""Step 5 — join registry, changelog and call-site facts into a ranked verdict.

Reads one JSON object per line, each merging what the earlier steps learned
about a single dependency, and emits the canonical result. Input comes from a
file when a path is given and from stdin otherwise -- a rote step has no TTY,
so the file form is what makes this capturable and runnable as a step.

The ranking rule, and the reason the Play is worth running:

  ACT      breaking changes AND you import it directly.       -> your problem, today
  REVIEW   you import it directly, but breaking status is
           UNKNOWN because notes could not be read.           -> nobody checked; you decide
  SAFE     outdated, but you never import it directly, or
           the notes were read and were clean.                -> bump it blind
  CURRENT  already at the latest version.

REVIEW exists so an unreadable changelog can never be laundered into "safe".
A rate-limited run reports more REVIEW rows; it never reports fewer ACT rows.
"""
import json
import sys

FS = chr(31)
RS = chr(30)

ORDER = {"ACT": 0, "REVIEW": 1, "SAFE": 2, "CURRENT": 3}
GAP_WEIGHT = {"major": 0, "minor": 1, "patch": 2, "none": 3, "unknown": 4, "ahead": 5}


def die(msg):
    print(f"compute_verdict: {msg}", file=sys.stderr)
    raise SystemExit(2)


def classify(rec):
    if not rec.get("outdated"):
        return "CURRENT", "already current"
    direct = bool(rec.get("direct"))
    checked = bool(rec.get("checked"))
    breaking = bool(rec.get("breaking"))

    # `scanned` defaults true so hand-written records behave as before. It is
    # false only when a merge saw no call-site payload for this dependency:
    # nobody looked, which is an unknown and must never read as "safe".
    if not rec.get("scanned", True):
        return "REVIEW", "call sites not scanned; import status unknown"
    if not direct:
        return "SAFE", "not imported directly; transitive"
    if breaking:
        return "ACT", rec.get("markers") or "breaking changes in range"
    if not checked:
        return "REVIEW", rec.get("warning") or "release notes unavailable; status unknown"
    return "SAFE", "notes read, no breaking markers"


def first_site(packed):
    """`path:line` of the first packed call site, or empty."""
    if not packed:
        return ""
    head = packed.split(RS)[0].split(FS)
    return f"{head[0]}:{head[1]}" if len(head) >= 2 and head[0] else ""


def merge_step_outputs(blobs):
    """Fold raw step payloads into one record per dependency.

    This is what lets the join be fed by DAG value edges instead of a file
    somebody built by hand: each upstream step's stdout arrives as one argv
    scalar and is matched up here.

    Registry and call-site payloads are keyed by (ecosystem, name). Changelog
    payloads are not -- they only know the repository -- so they are joined on
    the `repo` the registry step reported.
    """
    deps, changelogs, scanned = {}, {}, set()

    for raw in blobs:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            die(f"step output is not valid JSON: {exc}")
        if not isinstance(payload, dict):
            die("step output is not a JSON object")

        if "checked" in payload and "name" not in payload:
            if payload.get("repo"):
                changelogs[payload["repo"]] = payload
            continue

        eco, name = payload.get("ecosystem"), payload.get("name")
        if not eco or not name:
            continue                      # manifest summaries carry neither
        key = (eco, name)
        rec = deps.setdefault(key, {"ecosystem": eco, "name": name})
        for field in ("current", "latest", "gap", "outdated", "repo",
                      "direct", "files", "first_site"):
            if field in payload:
                rec[field] = payload[field]
        if "direct" in payload:
            scanned.add(key)
            if not rec.get("first_site"):
                rec["first_site"] = first_site(payload.get("packed", ""))

    for key, rec in deps.items():
        rec["scanned"] = key in scanned
        notes = changelogs.get(rec.get("repo") or "")
        if notes:
            rec["checked"] = bool(notes.get("checked"))
            rec["breaking"] = bool(notes.get("breaking"))
            rec["markers"] = notes.get("markers", "")
            if notes.get("warning"):
                rec["warning"] = notes["warning"]

    return [deps[key] for key in sorted(deps)]


def open_input():
    """The records file named on argv, or stdin when no path is given."""
    if len(sys.argv) < 2:
        return sys.stdin, False
    try:
        return open(sys.argv[1], encoding="utf-8"), True
    except OSError as exc:
        # A named file that cannot be read is a broken invocation, not an
        # expected absence: failing closed beats triaging zero dependencies
        # and reporting "nothing to triage".
        die(f"cannot read {sys.argv[1]}: {exc}")


def main():
    if sys.argv[1:2] == ["--from-steps"]:
        emit_report(merge_step_outputs(sys.argv[2:]))
        return

    stream, opened = open_input()
    records = []
    for line_no, line in enumerate(stream, 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            die(f"line {line_no} is not valid JSON: {exc}")
    if opened:
        stream.close()

    emit_report(records)


def emit_report(records):
    if not records:
        sys.stdout.write(json.dumps({
            "ok": True, "warning": "no dependency records on input",
            "total": 0, "act": 0, "review": 0, "safe": 0, "current": 0,
            "headline": "nothing to triage", "packed": "",
        }) + "\n")
        raise SystemExit(0)

    rows = []
    for rec in records:
        tier, why = classify(rec)
        rows.append({
            "tier": tier,
            "ecosystem": rec.get("ecosystem", "?"),
            "name": rec.get("name", "?"),
            "current": rec.get("current", ""),
            "latest": rec.get("latest", ""),
            "gap": rec.get("gap", "unknown"),
            "direct": bool(rec.get("direct")),
            "files": rec.get("files", 0),
            "why": why,
            "site": rec.get("first_site", ""),
        })

    rows.sort(key=lambda r: (ORDER[r["tier"]], GAP_WEIGHT.get(r["gap"], 9), r["name"]))
    counts = {t: sum(1 for r in rows if r["tier"] == t) for t in ORDER}
    outdated = counts["ACT"] + counts["REVIEW"] + counts["SAFE"]

    if counts["ACT"]:
        headline = (f"{counts['ACT']} of {len(rows)} dependencies have breaking changes "
                    f"in code you actually call")
    elif counts["REVIEW"]:
        headline = (f"no confirmed breaking changes, but {counts['REVIEW']} "
                    f"could not be verified")
    elif outdated:
        headline = f"{outdated} outdated, none of them breaking for your code"
    else:
        headline = "everything current"

    packed = RS.join(FS.join([
        r["tier"], r["ecosystem"], r["name"], r["current"] or "-", r["latest"] or "-",
        r["gap"], str(r["files"]), r["why"], r["site"],
    ]) for r in rows)

    sys.stdout.write(json.dumps({
        "ok": True,
        "total": len(rows),
        "act": counts["ACT"], "review": counts["REVIEW"],
        "safe": counts["SAFE"], "current": counts["CURRENT"],
        "outdated": outdated,
        "headline": headline,
        "packed": packed,
    }) + "\n")


if __name__ == "__main__":
    main()
