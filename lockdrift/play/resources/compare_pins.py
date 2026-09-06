#!/usr/bin/env python3
"""Join the three readings and say which dependencies would change on install.

    compare_pins.py --from-steps <declared_json> <locked_json> <installed_json>

The readers touch no shared state, so they are parallel root steps and this is
the fan-in. Each arrives as one argv scalar.

  DRIFT      the sources that were read disagree, and your next install acts on it
  UNLOCKED   declared, lockfiles were read, and nothing pins it
  UNCHECKED  a source needed for a full verdict was not readable or not observed
  SYNCED     all three were read and all three agree

The invariant, and the only reason to trust the output: a source that was not
read is never reported as agreement. No node_modules means the installed state
was not observed, so those rows are UNCHECKED -- never SYNCED. Running this on a
fresh clone yields MORE unchecked rows, never fewer warnings.

Range evaluation is deliberately narrow. Exact pins, caret, tilde and a single
comparator are evaluated; anything else -- unions, hyphen ranges, git and file
references, workspace protocols -- is reported UNCHECKED rather than guessed. A
false DRIFT costs more trust than a missed one.
"""
import json
import re
import sys

FS = chr(31)
RS = chr(30)

ORDER = {"DRIFT": 0, "UNLOCKED": 1, "UNCHECKED": 2, "SYNCED": 3}


def die(msg):
    print(f"compare_pins: {msg}", file=sys.stderr)
    raise SystemExit(2)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    raise SystemExit(0)


def scrub(value):
    return str(value).replace(FS, " ").replace(RS, " ")


def payload_of(arg, expect):
    """One reader's stdout, however the value edge delivered it."""
    text = (arg or "").strip()
    if not text:
        die(f"the {expect} step produced no output")
    if not text.startswith("{"):
        die(f"the {expect} step's output is not a JSON object")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        if not text.endswith("}"):
            die(f"the {expect} payload ends mid-value at {len(text):,} bytes, so "
                f"its dependencies past the cut were never seen. Failing closed "
                f"rather than comparing a partial list.")
        die(f"the {expect} payload will not parse as JSON: {exc}")
    if doc.get("source") != expect:
        die(f"expected the {expect} reading, got {doc.get('source')!r}")
    return doc


def rows_of(doc):
    """(ecosystem, name-lowered) -> (name, value, path, extra)."""
    table = {}
    for chunk in (doc.get("packed") or "").split(RS):
        if not chunk:
            continue
        fields = (chunk.split(FS) + ["", "", "", ""])[:5]
        eco, name, value, path, extra = fields
        table[(eco, name.lower())] = (name, value, path, extra)
    return table


# --- range evaluation, narrow on purpose -----------------------------------

VERSION = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parts(version):
    m = VERSION.match(str(version or ""))
    if not m:
        return None
    return tuple(int(g) if g else 0 for g in m.groups())


def within(version, low, high):
    """low <= version < high, either bound optional."""
    v = parts(version)
    if v is None:
        return None
    if low is not None and v < low:
        return False
    if high is not None and v >= high:
        return False
    return True


def satisfies(version, spec):
    """True / False / None when the range form is not evaluated."""
    spec = (spec or "").strip()
    if spec in ("", "*", "x", "X", "latest", "any"):
        return True
    if any(token in spec for token in ("||", " - ", "://", "file:", "git+",
                                       "workspace:", "link:", "npm:", ",")):
        return None
    if spec.count(" ") and not spec.startswith(("<", ">", "=", "~", "^")):
        return None

    # Strip the operator before parsing: parts() reads versions, not ranges.
    # Leaving it on made every caret range look unevaluable, which silently
    # turned a real out-of-range pin into UNCHECKED.
    head = parts(spec.lstrip("^~<>=v ").strip())

    if spec.startswith("^"):
        if head is None:
            return None
        major, minor, patch = head
        if major:
            return within(version, head, (major + 1, 0, 0))
        if minor:
            return within(version, head, (0, minor + 1, 0))
        return within(version, head, (0, 0, patch + 1))
    if spec.startswith("~") and not spec.startswith("~="):
        if head is None:
            return None
        major, minor, _patch = head
        return within(version, head, (major, minor + 1, 0))
    if spec.startswith("~="):                        # PEP 440 compatible release
        if head is None:
            return None
        major, minor, _patch = head
        return within(version, head, (major, minor + 1, 0))
    if spec.startswith(">="):
        return within(version, parts(spec[2:]), None)
    if spec.startswith("<="):
        v, bound = parts(version), parts(spec[2:])
        return None if v is None or bound is None else v <= bound
    if spec.startswith(">"):
        v, bound = parts(version), parts(spec[1:])
        return None if v is None or bound is None else v > bound
    if spec.startswith("<"):
        return within(version, None, parts(spec[1:]))
    if re.match(r"^[=v]*\d", spec):                  # a bare or == pin
        v = parts(version)
        return None if v is None or head is None else v == head
    return None


# --- the verdict ------------------------------------------------------------

def classify(dep, locks_read, installed_observed):
    """(tier, reason, compared) for one declared dependency."""
    spec, locked, installed = dep["spec"], dep["locked"], dep["installed"]

    if locked is None:
        if not locks_read:
            return ("UNCHECKED", "no lockfile was read, so nothing here is pinned "
                                 "or verifiable", "manifest")
        return ("UNLOCKED", "declared but absent from the lockfile; the version is "
                            "whatever the day resolves", "manifest+lock")

    in_range = satisfies(locked, spec)
    if in_range is False:
        return ("DRIFT", f"lock pins {locked}, outside the declared {spec}; the next "
                         f"resolve moves it", "manifest+lock")

    if installed is not None:
        if installed != locked:
            return ("DRIFT", f"lock pins {locked}, installed is {installed}; a clean "
                             f"install changes what you are running", "all three")
        if in_range is None:
            return ("UNCHECKED", f"lock and install agree on {locked}, but the "
                                 f"declared range {spec} was not evaluated",
                    "lock+installed")
        return ("SYNCED", f"manifest, lock and install all agree on {locked}",
                "all three")

    if not installed_observed:
        return ("UNCHECKED", f"lock pins {locked}, but no install tree was observed, "
                             f"so nothing is claimed about what is on disk",
                "manifest+lock")
    # Absent from a tree that WAS read. For a production dependency installing
    # would add it, which is drift. For a dev dependency the tree may simply be
    # a production install, and guessing which would be inventing evidence.
    if dep.get("lock_scope") == "dev":
        return ("UNCHECKED", f"lock pins {locked}; absent from the install tree, but "
                             f"it is a dev dependency and this may be a production "
                             f"install", "manifest+lock")
    return ("DRIFT", f"lock pins {locked}; nothing is installed, so installing would "
                     f"add it", "all three")


def render(rows, headline, sources):
    if not rows:
        return f"{headline}\n\n{sources}"
    width = {
        "name": max(len(r["name"]) for r in rows),
        "spec": max(len(r["spec"] or "*") for r in rows),
    }
    lines = [headline, "", sources, ""]
    for r in rows:
        lines.append(
            f'  {r["tier"]:<9} {r["ecosystem"]:<5} {r["name"]:<{width["name"]}}  '
            f'{(r["spec"] or "*"):<{width["spec"]}}  '
            f'lock {r["locked"] or "-":<12} installed {r["installed"] or "-"}'.rstrip())
        lines.append(f'  {"":<9} {r["why"]}')
    return "\n".join(lines)


def main():
    argv = sys.argv[1:]
    if argv[:1] != ["--from-steps"] or len(argv) < 4:
        die("usage: compare_pins.py --from-steps <declared> <locked> <installed>")

    declared_doc = payload_of(argv[1], "declared")
    locked_doc = payload_of(argv[2], "locked")
    installed_doc = payload_of(argv[3], "installed")

    declared = rows_of(declared_doc)
    locked = rows_of(locked_doc)
    installed = rows_of(installed_doc)

    locks_read = bool(locked_doc.get("lockfiles"))
    installed_observed = bool(installed_doc.get("observed"))

    if not declared:
        emit({
            "ok": True,
            "warning": declared_doc.get("warning") or "no declared dependencies found",
            "total": 0, "drift": 0, "unlocked": 0, "unchecked": 0, "synced": 0,
            "headline": "nothing declared to compare",
            "report": "nothing declared to compare",
            "packed": "",
        })

    rows = []
    for key in sorted(declared):
        eco, _lowered = key
        name, spec, manifest, _section = declared[key]
        lock_entry = locked.get(key)
        install_entry = installed.get(key)
        dep = {
            "spec": spec,
            "locked": lock_entry[1] if lock_entry else None,
            "lock_scope": lock_entry[3] if lock_entry else "",
            "installed": install_entry[1] if install_entry else None,
        }
        tier, why, compared = classify(dep, locks_read, installed_observed)
        rows.append({
            "tier": tier, "ecosystem": eco, "name": name, "spec": spec,
            "locked": dep["locked"], "installed": dep["installed"],
            "manifest": manifest, "why": why, "compared": compared,
        })

    rows.sort(key=lambda r: (ORDER[r["tier"]], r["ecosystem"], r["name"]))
    counts = {tier: sum(1 for r in rows if r["tier"] == tier) for tier in ORDER}

    if counts["DRIFT"]:
        headline = (f"{counts['DRIFT']} of {len(rows)} dependencies would change if "
                    f"you installed right now")
    elif counts["UNLOCKED"]:
        headline = (f"nothing drifted, but {counts['UNLOCKED']} dependencies are not "
                    f"pinned by any lockfile")
    elif counts["UNCHECKED"]:
        headline = (f"no drift found in what could be read, and {counts['UNCHECKED']} "
                    f"dependencies could not be fully checked")
    else:
        headline = f"all {len(rows)} dependencies agree across manifest, lock and install"

    sources = (f"read: {declared_doc.get('manifests') or 'no manifest'}"
               f" | {locked_doc.get('lockfiles') or 'no lockfile'}"
               f" | {installed_doc.get('trees', 0)} install tree(s)"
               f"{'' if installed_observed else ' — installed state NOT observed'}")

    packed = RS.join(FS.join(scrub(v) for v in [
        r["tier"], r["ecosystem"], r["name"], r["spec"] or "*",
        r["locked"] or "-", r["installed"] or "-", r["compared"], r["why"],
    ]) for r in rows)

    emit({
        "ok": True,
        "total": len(rows),
        "drift": counts["DRIFT"], "unlocked": counts["UNLOCKED"],
        "unchecked": counts["UNCHECKED"], "synced": counts["SYNCED"],
        "installed_observed": installed_observed,
        "headline": headline,
        "report": render(rows, headline, sources),
        "packed": packed,
    })


if __name__ == "__main__":
    main()
