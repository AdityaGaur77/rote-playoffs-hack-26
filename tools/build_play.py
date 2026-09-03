#!/usr/bin/env python3
"""Generate the publishable Play from the step scripts.

main.ts carries ~59 KB of base64 -- the five step scripts, inlined so the Play
runs on a machine that has never seen this repository. Hand-maintaining that is
not possible, and hand-editing it after a step changes is how a published Play
silently goes stale. So the file is generated:

    python3 tools/build_play.py                 # write play/main.ts
    python3 tools/build_play.py --check         # fail if it is out of date

Re-run it after ANY change to steps/. The --check form is what stops a fix from
being tested locally and never reaching what was published.

---------------------------------------------------------------------------
THREE TOKENS TO CONFIRM BEFORE THE FIRST PUBLISH

Everything else here is mechanical. These three are rote's own syntax, and the
authoritative source is the local install, not this file:

    rote guidance play crystallization | cat        # pipe to cat: it pages

A faster answer, if a Play that already works is on this machine: read the one
that used a parameter, e.g. ~/.rote/flows/dns-propagation-check/main.ts, and
copy its forms verbatim.

Get them right once, correct the three constants below, re-run, and the whole
file is correct. Get them wrong and `rote play lint` will say so before anyone
sees it.
---------------------------------------------------------------------------
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEPS = os.path.join(ROOT, "steps")
OUT = os.path.join(ROOT, "play", "main.ts")

# 1. How a declared parameter is interpolated into a step's argv.
PARAM = "${{{name}}}"

# 2. How one step's output is referenced by another. The handoff records this
#    as `@step{.path}` resolving against the unwrapped payload; for a
#    process.exec step the body is the exec result, so `.stdout.text`.
EDGE = "@{step}.stdout.text"

# 3. How the presentation body reaches a step's output. Same reference, read
#    from the body rather than from an argv slot.
BODY_READ = 'steps.rank_verdict.stdout.json.report'

NAME = "upgrade-impact-triage"
VERSION = "0.1.0"
AUTHOR = "adityagaur <adityagaur12077@gmail.com>"

DESCRIPTION = (
    "Of your outdated dependencies, which ones ship breaking changes in code "
    "you actually import? Reads every manifest under <root>, resolves current "
    "versus latest from npm, PyPI or crates.io, reads the GitHub release notes "
    "between the two, and finds the files and line numbers that import each "
    "package. Ranks the result ACT (breaking, and you call it), REVIEW (you "
    "call it, but the notes could not be read), SAFE (transitive, or the notes "
    "were read and were clean) or CURRENT. An unreadable changelog reports as "
    "REVIEW, never as SAFE, so a rate-limited run produces more rows to check "
    "by hand and never fewer warnings. Standard library Python only; "
    "GITHUB_TOKEN is optional and raises the API rate limit."
)

# name -> (script, extra argv after the inlined program, depends_on)
# The chain is linear: each stage fills its own columns of the carrier record
# and passes the rest through, so nothing has to exist on disk between steps.
GRAPH = [
    ("find_dependencies", "parse_manifest",   ["root"],                    []),
    ("resolve_versions",  "fetch_registry",   ["--batch", "edge"],         ["find_dependencies"]),
    ("locate_callsites",  "find_callsites",   ["--batch", "root", "edge"], ["resolve_versions"]),
    ("read_changelogs",   "fetch_changelog",  ["--batch", "edge"],         ["locate_callsites"]),
    ("rank_verdict",      "compute_verdict",  ["--batch", "edge"],         ["read_changelogs"]),
]

BOOTSTRAP = "import base64;exec(base64.b64decode('{}').decode())"


def inlined(script):
    with open(os.path.join(STEPS, f"{script}.py"), "rb") as handle:
        return BOOTSTRAP.format(base64.b64encode(handle.read()).decode("ascii"))


def argv_for(script, spec, parents):
    argv = ["python3", "-c", inlined(script)]
    for token in spec:
        if token == "root":
            argv.append(PARAM.format(name="root"))
        elif token == "edge":
            argv.append(EDGE.format(step=parents[0]))
        else:
            argv.append(token)
    return argv


def yaml_block(lines, indent=" * "):
    return "\n".join(f"{indent}{line}".rstrip() for line in lines)


def frontmatter():
    lines = [
        "@rote-frontmatter",
        "---",
        f"name: {NAME}",
        f'version: "{VERSION}"',
        f"description: {json.dumps(DESCRIPTION)}",
        "provenance:",
        f"  author: {AUTHOR}",
        "parameters:",
        "  - name: root",
        "    type: string",
        "    required: true",
        "    description: 'Path to the project to triage. Use . for the current directory.'",
        "metadata:",
        '  rote_version: "0.78.0"',
        "  status: draft",
        "  kind: atomic",
        "  flow_type: parallel",
        "  execution_model: steps_with_presentation",
        "  requires_sessions: false",
        "steps:",
    ]
    for step, script, spec, parents in GRAPH:
        lines.append(f"  {step}:")
        lines.append("    type: process.exec")
        lines.append("    argv:")
        for arg in argv_for(script, spec, parents):
            lines.append(f"    - {json.dumps(arg)}")
        if parents:
            lines.append("    depends_on:")
            for parent in parents:
                lines.append(f"    - {parent}")
    lines.append("---")
    return lines


BODY = f"""
// The report is rendered by the final step, in Python, under test -- so this
// body has one job. process.stdout.write, never console.log.
const report = {BODY_READ};
process.stdout.write((report || "nothing to triage") + "\\n");
"""


def build():
    block = yaml_block(frontmatter())
    # A literal */ anywhere in the frontmatter closes the comment early and the
    # rest of the Play becomes syntax. base64 cannot produce one; prose can.
    if "*/" in block:
        raise SystemExit("build_play: frontmatter contains */, which would "
                         "close the comment block early")
    return ("#!/usr/bin/env -S rote play run\n"
            "/**\n" + block + "\n */\n" + BODY)


def main():
    text = build()
    if "--check" in sys.argv[1:]:
        try:
            with open(OUT, encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            print(f"build_play: {OUT} does not exist; run without --check",
                  file=sys.stderr)
            raise SystemExit(2)
        if current != text:
            print("build_play: play/main.ts is stale — a step changed since it "
                  "was generated. Re-run: python3 tools/build_play.py",
                  file=sys.stderr)
            raise SystemExit(2)
        print("play/main.ts is up to date")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"wrote {os.path.relpath(OUT, ROOT)}  "
          f"({len(text):,} bytes, {len(GRAPH)} steps)")
    print("confirm PARAM, EDGE and BODY_READ against `rote guidance play "
          "crystallization` before publishing")


if __name__ == "__main__":
    main()
