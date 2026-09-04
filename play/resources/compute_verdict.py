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


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def classify(rec):
    # An unfilled fact is UNKNOWN, never a clean bill of health. A stage that
    # did not run must widen REVIEW; it must never narrow it, because the whole
    # value of this Play is that "safe to bump" means somebody checked.
    if rec.get("outdated_unknown"):
        return "REVIEW", "version never resolved; status unknown"
    if not rec.get("outdated"):
        return "CURRENT", "already current"
    if rec.get("direct_unknown"):
        return "REVIEW", "call sites never scanned; status unknown"

    direct = bool(rec.get("direct"))
    checked = bool(rec.get("checked"))
    breaking = bool(rec.get("breaking"))

    if not direct:
        return "SAFE", "not imported directly; transitive"
    if breaking:
        return "ACT", rec.get("markers") or "breaking changes in range"
    if not checked:
        why = rec.get("warning") or "release notes unavailable; status unknown"
        # Markers found without reading the notes -- a major version bump -- are
        # still evidence. Surfacing them keeps a degraded row informative
        # without promoting it out of REVIEW.
        if rec.get("markers"):
            why = f"{why} ({rec['markers']})"
        return "REVIEW", why
    return "SAFE", "notes read, no breaking markers"


def record_from_row(row):
    """A carrier row as the record classify() expects, unknowns preserved."""
    return {
        "ecosystem": row[0],
        "name": row[1],
        "current": row[2],
        "latest": row[3],
        "gap": row[5] or "unknown",
        "outdated": row[6] == "1",
        "outdated_unknown": row[6] == "",
        "direct": row[7] == "1",
        "direct_unknown": row[7] == "",
        "files": int(row[8]) if row[8].isdigit() else 0,
        "first_site": row[9],
        "checked": row[10] == "1",
        "breaking": row[11] == "1",
        "markers": row[12],
    }


def read_records():
    """Records from --batch, from a named file, or from stdin.

    --batch is the form the Play uses: the upstream step's output arrives whole
    as one argv scalar, so nothing has to exist on disk and the chain works on a
    machine that has never seen this repository.
    """
    argv = sys.argv[1:]
    if argv and argv[0] == "--batch":
        if len(argv) < 2:
            die("usage: compute_verdict.py --batch <upstream payload>")
        return [record_from_row(row) for row in unpack(upstream_packed(argv[1]))]

    stream, opened = None, False
    if argv:
        try:
            stream, opened = open(argv[0], encoding="utf-8"), True
        except OSError as exc:
            # A named file that cannot be read is a broken invocation, not an
            # expected absence: failing closed beats triaging zero dependencies
            # and reporting "nothing to triage".
            die(f"cannot read {argv[0]}: {exc}")
    else:
        stream = sys.stdin

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
    return records


def render(rows, headline):
    """A plain-text report, built here rather than in the Play body.

    The Play's presentation layer has one job -- print this string -- so the
    formatting is covered by the same tests as the ranking it presents.
    """
    if not rows:
        return headline
    width = {
        "name": max(len(r["name"]) for r in rows),
        "ver": max(len(f'{r["current"] or "-"} -> {r["latest"] or "-"}') for r in rows),
        "gap": max(len(r["gap"]) for r in rows),
    }
    lines = [headline, ""]
    for r in rows:
        versions = f'{r["current"] or "-"} -> {r["latest"] or "-"}'
        files = f'{r["files"]} file' + ("s" if r["files"] != 1 else "")
        lines.append(
            f'  {r["tier"]:<7} {r["ecosystem"]:<6} {r["name"]:<{width["name"]}}  '
            f'{versions:<{width["ver"]}}  {r["gap"]:<{width["gap"]}}  '
            f'{files:>8}  {r["site"] or "-"}'.rstrip())
        lines.append(f'  {"":<7} {r["why"]}')
    return "\n".join(lines)


def main():
    records = read_records()

    if not records:
        emit({
            "ok": True, "warning": "no dependency records on input",
            "total": 0, "act": 0, "review": 0, "safe": 0, "current": 0,
            "headline": "nothing to triage", "report": "nothing to triage",
            "packed": "",
        })

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

    emit({
        "ok": True,
        "report": render(rows, headline),
        "total": len(rows),
        "act": counts["ACT"], "review": counts["REVIEW"],
        "safe": counts["SAFE"], "current": counts["CURRENT"],
        "outdated": outdated,
        "headline": headline,
        "packed": packed,
    })


if __name__ == "__main__":
    main()
