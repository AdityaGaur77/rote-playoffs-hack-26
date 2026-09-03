#!/usr/bin/env python3
"""Generate the publishable Play from the step scripts.

    python3 tools/build_play.py              # write play/main.ts
    python3 tools/build_play.py --check      # fail if it is out of date
    python3 tools/build_play.py --base64     # inline as base64 instead of source

Re-run after ANY change to steps/. The --check form runs in the test suite,
which is what stops a fix from being tested locally and never reaching what was
published.

Every step script is embedded in the frontmatter as literal Python, the way
modiqo/dns-propagation-check embeds its own. That costs about the same bytes as
base64 and buys the thing base64 destroys: someone inspecting the Play before
running it can read exactly what it will do. `--base64` keeps the opaque form
available in case a parser objects to something in the source.

The generator verifies its own output: it strips the comment prefix, parses the
frontmatter as YAML, and asserts every embedded script round-trips to the exact
bytes on disk. A Play that does not survive that is not written.
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEPS = os.path.join(ROOT, "steps")
OUT = os.path.join(ROOT, "play", "main.ts")

NAME = "upgrade-impact-triage"
VERSION = "0.1.0"
AUTHOR = "adityagaur <adityagaur12077@gmail.com>"
SOURCE = "https://semver.org/"

DESCRIPTION = (
    "Of your outdated dependencies, which ones ship breaking changes in code you "
    "actually import? Reads every manifest under root, resolves current versus "
    "latest from npm, PyPI or crates.io, reads the GitHub release notes between "
    "the two, and finds the files and line numbers that import each package. "
    "Ranks each dependency ACT (breaking changes, and you call it directly), "
    "REVIEW (you call it, but the notes could not be read), SAFE (transitive, or "
    "the notes were read and were clean) or CURRENT. An unreadable changelog "
    "reports as REVIEW and never as SAFE, so a rate-limited or offline run "
    "produces more rows to check by hand and never fewer warnings. Standard "
    "library Python only; GITHUB_TOKEN is optional and raises the API rate limit."
)

TAGS = [
    "domain-software-development",
    "software-development",
    "job-dependency-upgrade",
    "tool-package-registry",
    "tool-github",
    "effect-read-only",
]

# step, script, timeout, extra argv after the program, depends_on
#
# The chain is linear: each stage fills its own columns of the carrier record
# and passes the rest through, so nothing has to exist on disk between steps.
# Timeouts are generous on the two stages that make one network call per
# dependency; a 47-dependency project is the case that matters.
GRAPH = [
    ("find_dependencies", "parse_manifest",  30_000, ["root"], []),
    ("resolve_versions", "fetch_registry",  180_000, ["--batch", "edge"], ["find_dependencies"]),
    ("locate_callsites", "find_callsites",   90_000, ["--batch", "root", "edge"], ["resolve_versions"]),
    ("read_changelogs", "fetch_changelog",  240_000, ["--batch", "edge"], ["locate_callsites"]),
    ("rank_verdict", "compute_verdict",      15_000, ["--batch", "edge"], ["read_changelogs"]),
]

STAGE_LABELS = {
    "find_dependencies": "manifests",
    "resolve_versions": "registry",
    "locate_callsites": "call sites",
    "read_changelogs": "release notes",
    "rank_verdict": "verdict join",
}

# rote's own syntax, as used by modiqo/dns-propagation-check v1.1.0:
#   a parameter is a bare $name
#   a value edge is @step{<jq over the step outcome>}
PARAM = "${name}"
EDGE = "@{step}{{$.stdout.text | fromjson | .packed}}"

BOOTSTRAP = "import base64;exec(base64.b64decode('{}').decode())"


def source_of(script):
    with open(os.path.join(STEPS, f"{script}.py"), encoding="utf-8") as handle:
        return handle.read()


def program(script, use_base64):
    if use_base64:
        blob = base64.b64encode(source_of(script).encode("utf-8")).decode("ascii")
        return BOOTSTRAP.format(blob)
    return source_of(script)


def tail_args(spec, parents):
    args = []
    for token in spec:
        if token == "root":
            args.append(PARAM.format(name="root"))
        elif token == "edge":
            args.append(EDGE.format(step=parents[0]))
        else:
            args.append(token)
    return args


def block_scalar(text, indent):
    """A literal YAML block scalar with an explicit indentation indicator.

    The indicator is what makes this safe: without it a first line that begins
    with a space would set the block's indentation implicitly and silently eat
    it. The leading blank line is deliberate and matches the reference Play.
    """
    pad = " " * indent
    lines = [f"{pad}- |2", ""]
    body = " " * (indent + 2)
    for line in text.split("\n"):
        lines.append(f"{body}{line}" if line else "")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def frontmatter(use_base64):
    lines = [
        "Upgrade Impact Triage",
        "",
        "Of your outdated dependencies, which ones will actually break you.",
        "",
        "@rote-frontmatter",
        "---",
        f"name: {NAME}",
        f"version: {VERSION}",
        f"description: {json.dumps(DESCRIPTION)}",
        f"source: {SOURCE}",
        "provenance:",
        f"  author: {AUTHOR}",
        "  tier: local",
        "  workspace: upgrade-impact-triage",
        "metadata:",
        '  rote_version: "0.78.0"',
        f'  version: "{VERSION}"',
        "  status: draft",
        "  kind: atomic",
        "  flow_type: parallel",
        "  execution_model: steps_with_presentation",
        "  format: typescript",
        "  requires_endpoints: []",
        "  requires_sessions: false",
        "  discoverability:",
        "    tags:",
    ]
    lines += [f"    - {tag}" for tag in TAGS]
    lines += [
        "parameters:",
        "- name: root",
        "  param_type: string",
        "  required: false",
        "  default: '.'",
        "  description: Path to the project to triage; defaults to the current directory",
        "  example: .",
        "  valid_values: null",
        "contract:",
        "  atomic: true",
        "  input:",
        "    type: none",
        "  output:",
        "    format: json",
        "    destination: stdout",
        "  composable: true",
        "steps:",
    ]
    for step, script, timeout, spec, parents in GRAPH:
        lines.append(f"  {step}:")
        lines.append("    type: process.exec")
        lines.append(f"    timeout_ms: {timeout}")
        if parents:
            lines.append("    depends_on:")
            lines += [f"    - {parent}" for parent in parents]
        lines.append("    argv:")
        lines.append("    - python3")
        lines.append("    - -c")
        lines += block_scalar(program(script, use_base64), 4)
        lines += [f"    - {json.dumps(arg)}" for arg in tail_args(spec, parents)]
    lines.append("---")
    return lines


def body():
    stages = ",\n".join(
        f'  ["{step}", "{STAGE_LABELS[step]}"]' for step, *_ in GRAPH)
    handles = "\n".join(
        f'  {step}: ctx.step(stepName("{step}")),' for step, *_ in GRAPH)
    return f'''
const {{ FlowOutput, loadPresentationContext, stepName }} =
  await import("__ROTE_PRESENTATION_SDK__");

type StageRow = {{ stage: string; label: string; state: string; note: string }};
type Verdict = {{
  total: number; act: number; review: number; safe: number; current: number;
  headline: string; report: string; warning?: string;
}};

const out = new FlowOutput();
const ctx = await loadPresentationContext();

const STAGES: Array<[string, string]> = [
{stages},
];
const STEP_HANDLES = {{
{handles}
}};

const bodyOf = (step: (typeof STEP_HANDLES)[keyof typeof STEP_HANDLES]): Record<string, unknown> | null => {{
  const outcome = step.outcome;
  if (outcome.status !== "completed" && outcome.status !== "restored") return null;
  const text = (outcome.output.body as {{ stdout?: {{ text?: string }} }})?.stdout?.text;
  if (typeof text !== "string" || !text.trim()) return null;
  try {{
    const parsed = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : null;
  }} catch {{
    return null;
  }}
}};

// The ledger is not decoration. When a stage degrades -- a rate-limited
// changelog read, an unreachable registry -- the rows it fed report REVIEW
// rather than SAFE, and this is where you see why.
const ledger: StageRow[] = [];
for (const [id, label] of STAGES) {{
  const step = STEP_HANDLES[id as keyof typeof STEP_HANDLES];
  const info = bodyOf(step);
  const status = step.outcome.status;
  let state: string;
  let note = "";
  if (info && (status === "completed" || status === "restored")) {{
    const degraded = typeof info["warning"] === "string";
    state = degraded ? "degraded" : "ok";
    note = degraded ? String(info["warning"]) : "";
  }} else if (status === "completed" || status === "restored") {{
    state = "degraded";
    note = "unparseable output";
  }} else if (status === "skipped" || status === "blocked") {{
    state = status;
    note = String((step.outcome.output as {{ reason?: string }}).reason ?? "");
  }} else {{
    state = "failed";
    note = String((step.outcome.output as {{ message?: string }}).message ?? "").slice(0, 80);
  }}
  ledger.push({{ stage: id, label, state, note }});
}}

const GLYPH: Record<string, string> = {{
  ok: "████████",
  degraded: "█████░░░",
  skipped: "░░░░░░░░",
  blocked: "░░░░░░░░",
  failed: "░░░░░░░░",
}};

const fallback: Verdict = {{
  total: 0, act: 0, review: 0, safe: 0, current: 0,
  headline: "no verdict",
  report: "The verdict join did not produce a report; see the stage ledger.",
}};
const verdictBody = bodyOf(STEP_HANDLES.rank_verdict);
const verdict: Verdict =
  verdictBody && typeof verdictBody["report"] === "string"
    ? (verdictBody as unknown as Verdict)
    : fallback;

const okCount = ledger.filter((r) => r.state === "ok").length;
const bar = "█".repeat(Math.round((okCount / ledger.length) * 24)).padEnd(24, "░");

const lines: string[] = [];
lines.push(`UPGRADE IMPACT  ${{String(ctx.params.root ?? ".")}}`);
lines.push("");
lines.push(`  stages  ${{bar}}  ${{okCount}}/${{ledger.length}} ok`);
for (const row of ledger) {{
  lines.push(`  ${{GLYPH[row.state] ?? GLYPH.failed}}  ${{row.label.padEnd(16)}}${{row.state}}${{row.note ? ` — ${{row.note}}` : ""}}`);
}}
lines.push("");
lines.push(verdict.report);
lines.push("");
lines.push("ACT = breaking changes in code you import directly. REVIEW = you import it,");
lines.push("but the release notes could not be read, so nobody has checked. An unreadable");
lines.push("changelog is never reported as SAFE.");

out.human(lines.join("\\n"));
out.summary(verdict.headline);
out.result({{ run_id: ctx.run.run_id, stages: ledger, ...verdict }});
'''


def build(use_base64=False):
    block = frontmatter(use_base64)
    rendered = "\n".join(f" * {line}".rstrip() for line in block)
    # A literal */ closes the comment early and the rest of the Play becomes
    # syntax. base64 cannot produce one; Python source can.
    if "*/" in rendered:
        raise SystemExit("build_play: frontmatter contains */, which would close "
                         "the comment block early")
    return ("#!/usr/bin/env -S rote play run\n/**\n" + rendered + "\n */\n" + body())


def verify(text, use_base64):
    """Parse the frontmatter back and prove every script survived the transport.

    A generator that emits YAML nobody parsed is a generator that ships broken
    Plays. This is the check that makes embedding literal source safe.
    """
    try:
        import yaml
    except ImportError:
        print("build_play: PyYAML not installed; skipping round-trip verification",
              file=sys.stderr)
        return

    inner = text.split("/**\n", 1)[1].split("\n */\n", 1)[0]
    stripped = "\n".join(
        line[3:] if line.startswith(" * ") else line[2:] if line.startswith(" *") else line
        for line in inner.split("\n"))
    doc = yaml.safe_load(stripped.split("---\n", 1)[1].rsplit("---", 1)[0])

    assert doc["name"] == NAME, "name did not survive"
    assert doc["description"].strip(), "description is empty"
    names = [step for step, *_ in GRAPH]
    assert list(doc["steps"]) == names, f"steps changed: {list(doc['steps'])}"

    for step, script, _timeout, spec, parents in GRAPH:
        argv = doc["steps"][step]["argv"]
        assert argv[0] == "python3" and argv[1] == "-c", f"{step}: argv shape"
        embedded = argv[2].lstrip("\n")
        expected = program(script, use_base64).rstrip("\n")
        assert embedded.rstrip("\n") == expected, (
            f"{step}: embedded program does not match steps/{script}.py")
        assert argv[3:] == tail_args(spec, parents), f"{step}: trailing args"
        assert doc["steps"][step].get("depends_on", []) == parents, f"{step}: edges"
    print(f"verified: {len(GRAPH)} steps parse and round-trip to their source")


def main():
    args = sys.argv[1:]
    use_base64 = "--base64" in args
    text = build(use_base64)
    verify(text, use_base64)

    if "--check" in args:
        try:
            with open(OUT, encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            print(f"build_play: {OUT} does not exist; run without --check",
                  file=sys.stderr)
            raise SystemExit(2)
        # Either inlining mode is a legitimate way to have built the file, so
        # accept whichever one reproduces it. Otherwise switching to --base64
        # would leave the staleness check permanently red.
        if current != text and current != build(not use_base64):
            print("build_play: play/main.ts is stale — a step changed since it was "
                  "generated. Re-run: python3 tools/build_play.py", file=sys.stderr)
            raise SystemExit(2)
        print("play/main.ts is up to date")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(text)
    form = "base64" if use_base64 else "literal source"
    print(f"wrote {os.path.relpath(OUT, ROOT)}  ({len(text):,} bytes, "
          f"{len(GRAPH)} steps, {form})")


if __name__ == "__main__":
    main()
