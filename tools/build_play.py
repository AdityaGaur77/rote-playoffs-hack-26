#!/usr/bin/env python3
"""Generate the publishable Play from the step scripts.

    python3 tools/build_play.py              # write play/main.ts + play/resources/
    python3 tools/build_play.py --check      # fail if either is out of date

Re-run after ANY change to steps/. The --check form runs in the test suite,
which is what stops a fix from being tested locally and never reaching what was
published.

The step scripts do NOT travel inside argv. rote caps an inline argv element at
256 characters and rejects one containing a line break:

    STEP_INLINE_CODE_PAYLOAD: argv[2] contains a line break and has 5343
    characters, above the 256-character inline limit. Keep `process.exec` argv
    as command structure: move static, non-secret, redistributable code under
    `resources/` and invoke it with a literal `@resource{...}` token.

So each script is published as a file under `play/resources/` and named in argv
by a resource token. That is better than either thing tried before it -- base64,
then literal source in the frontmatter -- because argv stays command structure
and someone inspecting the Play reads the steps as ordinary Python files.

The generator verifies its own output: it parses the frontmatter as YAML and
asserts no argv element breaks the inline limit, which is the rule that caught
the previous design.

Presentation fixtures are declared only when their files exist -- a declaration
with a missing target is a lint error, and the evidence comes from a real run
via tools/make_fixtures.py, never from anything synthesised here.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEPS = os.path.join(ROOT, "steps")
PLAY = os.path.join(ROOT, "play")
OUT = os.path.join(PLAY, "main.ts")
RESOURCES = os.path.join(PLAY, "resources")
FIXTURES = os.path.join(RESOURCES, "presentation-fixtures")

# rote's inline-argv limit, from the lint rule that rejected the previous design.
ARGV_LIMIT = 256

NAME = "upgrade-impact-triage"
VERSION = "0.1.3"
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

# rote's own syntax, as used by modiqo/dns-propagation-check v1.1.0 and as named
# by the linter: a parameter is a bare $name, a value edge is @step{<jq>}, and a
# published file is @resource{<name>}.
PARAM = "${name}"
EDGE = "@{step}{{$.stdout.text | fromjson | .packed}}"
RESOURCE = "@resource{{{name}}}"


def source_of(script):
    with open(os.path.join(STEPS, f"{script}.py"), encoding="utf-8") as handle:
        return handle.read()


def argv_for(script, spec, parents):
    argv = ["python3", RESOURCE.format(name=f"{script}.py")]
    for token in spec:
        if token == "root":
            argv.append(PARAM.format(name="root"))
        elif token == "edge":
            argv.append(EDGE.format(step=parents[0]))
        else:
            argv.append(token)
    return argv


def frontmatter():
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
        lines += [f"    - {json.dumps(arg)}" for arg in argv_for(script, spec, parents)]

    # Declared only when the evidence exists. A declaration whose target is
    # missing is a lint error, and the evidence comes from a real run
    # (tools/make_fixtures.py), not from anything this file can synthesise.
    if fixtures_present():
        lines.append("presentation_fixtures:")
        for step, *_ in GRAPH:
            lines.append(f"  {step}: resources/presentation-fixtures/{step}/fixture.yaml")
    lines.append("---")
    return lines


def fixtures_present():
    """True when every step has a complete fixture triple on disk."""
    return all(
        os.path.exists(os.path.join(FIXTURES, step, name))
        for step, *_ in GRAPH
        for name in ("fixture.yaml", "stdout.json", "stderr.txt"))


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


def build():
    rendered = "\n".join(f" * {line}".rstrip() for line in frontmatter())
    # A literal */ closes the comment early and the rest of the Play becomes
    # syntax.
    if "*/" in rendered:
        raise SystemExit("build_play: frontmatter contains */, which would close "
                         "the comment block early")
    return ("#!/usr/bin/env -S rote play run\n/**\n" + rendered + "\n */\n" + body())


def verify(text):
    """Parse the frontmatter back and prove the Play is publishable.

    A generator that emits YAML nobody parsed is a generator that ships broken
    Plays. The argv-limit assertion is here because the previous design passed
    every test in this repo and was rejected by rote's linter.
    """
    try:
        import yaml
    except ImportError:
        print("build_play: PyYAML not installed; skipping frontmatter verification",
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
        assert argv == argv_for(script, spec, parents), f"{step}: argv"
        assert doc["steps"][step].get("depends_on", []) == parents, f"{step}: edges"
        for i, arg in enumerate(argv):
            assert "\n" not in arg, f"{step}: argv[{i}] contains a line break"
            assert len(arg) <= ARGV_LIMIT, (
                f"{step}: argv[{i}] is {len(arg)} chars, over the "
                f"{ARGV_LIMIT}-character inline limit")
    print(f"verified: {len(GRAPH)} steps parse, every argv element within the "
          f"{ARGV_LIMIT}-character limit")


def write_resources():
    """Publish each step as a file the Play can name, and prune stale ones."""
    os.makedirs(RESOURCES, exist_ok=True)
    wanted = {f"{script}.py" for _step, script, *_rest in GRAPH}
    for name in sorted(os.listdir(RESOURCES)):
        if name not in wanted and name != "presentation-fixtures":
            os.remove(os.path.join(RESOURCES, name))
    for _step, script, *_rest in GRAPH:
        shutil.copyfile(os.path.join(STEPS, f"{script}.py"),
                        os.path.join(RESOURCES, f"{script}.py"))
    return sorted(wanted)


def resources_current():
    if not os.path.isdir(RESOURCES):
        return False, "play/resources/ does not exist"
    wanted = {f"{script}.py" for _step, script, *_rest in GRAPH}
    for _step, script, *_rest in GRAPH:
        published = os.path.join(RESOURCES, f"{script}.py")
        if not os.path.exists(published):
            return False, f"play/resources/{script}.py is missing"
        with open(published, encoding="utf-8") as handle:
            if handle.read() != source_of(script):
                return False, f"play/resources/{script}.py differs from steps/{script}.py"
    extra = sorted(set(os.listdir(RESOURCES)) - wanted - {"presentation-fixtures"})
    if extra:
        return False, f"play/resources/ carries files no step names: {extra}"
    return True, ""


def main():
    args = sys.argv[1:]
    text = build()
    verify(text)

    if "--check" in args:
        try:
            with open(OUT, encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            print(f"build_play: {OUT} does not exist; run without --check",
                  file=sys.stderr)
            raise SystemExit(2)
        if current != text:
            print("build_play: play/main.ts is stale — re-run: "
                  "python3 tools/build_play.py", file=sys.stderr)
            raise SystemExit(2)
        ok, why = resources_current()
        if not ok:
            print(f"build_play: {why} — re-run: python3 tools/build_play.py",
                  file=sys.stderr)
            raise SystemExit(2)
        print("play/main.ts and play/resources/ are up to date")
        return

    os.makedirs(PLAY, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(text)
    published = write_resources()
    print(f"wrote {os.path.relpath(OUT, ROOT)}  ({len(text):,} bytes, {len(GRAPH)} steps)")
    print(f"wrote {os.path.relpath(RESOURCES, ROOT)}/  ({len(published)} scripts)")
    if fixtures_present():
        print(f"declared presentation_fixtures for {len(GRAPH)} steps")
    else:
        print("no presentation fixtures yet — lint will report "
              "PRESENTATION_FIXTURE_REQUIRED.\n"
              "  build them from a run: python3 tools/make_fixtures.py <input.json>")


if __name__ == "__main__":
    main()
