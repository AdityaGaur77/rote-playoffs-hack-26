#!/usr/bin/env -S rote play run
/**
 * Upgrade Impact Triage
 *
 * Of your outdated dependencies, which ones will actually break you.
 *
 * @rote-frontmatter
 * ---
 * name: upgrade-impact-triage
 * version: 0.1.2
 * description: "Of your outdated dependencies, which ones ship breaking changes in code you actually import? Reads every manifest under root, resolves current versus latest from npm, PyPI or crates.io, reads the GitHub release notes between the two, and finds the files and line numbers that import each package. Ranks each dependency ACT (breaking changes, and you call it directly), REVIEW (you call it, but the notes could not be read), SAFE (transitive, or the notes were read and were clean) or CURRENT. An unreadable changelog reports as REVIEW and never as SAFE, so a rate-limited or offline run produces more rows to check by hand and never fewer warnings. Standard library Python only; GITHUB_TOKEN is optional and raises the API rate limit."
 * source: https://semver.org/
 * provenance:
 *   author: adityagaur <adityagaur12077@gmail.com>
 *   tier: local
 *   workspace: upgrade-impact-triage
 * metadata:
 *   rote_version: "0.78.0"
 *   version: "0.1.2"
 *   status: draft
 *   kind: atomic
 *   flow_type: parallel
 *   execution_model: steps_with_presentation
 *   format: typescript
 *   requires_endpoints: []
 *   requires_sessions: false
 *   discoverability:
 *     tags:
 *     - domain-software-development
 *     - software-development
 *     - job-dependency-upgrade
 *     - tool-package-registry
 *     - tool-github
 *     - effect-read-only
 * parameters:
 * - name: root
 *   param_type: string
 *   required: false
 *   default: '.'
 *   description: Path to the project to triage; defaults to the current directory
 *   example: .
 *   valid_values: null
 * contract:
 *   atomic: true
 *   input:
 *     type: none
 *   output:
 *     format: json
 *     destination: stdout
 *   composable: true
 * steps:
 *   find_dependencies:
 *     type: process.exec
 *     timeout_ms: 30000
 *     argv:
 *     - "python3"
 *     - "@resource{parse_manifest.py}"
 *     - "$root"
 *   resolve_versions:
 *     type: process.exec
 *     timeout_ms: 180000
 *     depends_on:
 *     - find_dependencies
 *     argv:
 *     - "python3"
 *     - "@resource{fetch_registry.py}"
 *     - "--batch"
 *     - "@find_dependencies{$.stdout.text | fromjson | .packed}"
 *   locate_callsites:
 *     type: process.exec
 *     timeout_ms: 90000
 *     depends_on:
 *     - resolve_versions
 *     argv:
 *     - "python3"
 *     - "@resource{find_callsites.py}"
 *     - "--batch"
 *     - "$root"
 *     - "@resolve_versions{$.stdout.text | fromjson | .packed}"
 *   read_changelogs:
 *     type: process.exec
 *     timeout_ms: 240000
 *     depends_on:
 *     - locate_callsites
 *     argv:
 *     - "python3"
 *     - "@resource{fetch_changelog.py}"
 *     - "--batch"
 *     - "@locate_callsites{$.stdout.text | fromjson | .packed}"
 *   rank_verdict:
 *     type: process.exec
 *     timeout_ms: 15000
 *     depends_on:
 *     - read_changelogs
 *     argv:
 *     - "python3"
 *     - "@resource{compute_verdict.py}"
 *     - "--batch"
 *     - "@read_changelogs{$.stdout.text | fromjson | .packed}"
 * presentation_fixtures:
 *   find_dependencies: resources/presentation-fixtures/find_dependencies/fixture.yaml
 *   resolve_versions: resources/presentation-fixtures/resolve_versions/fixture.yaml
 *   locate_callsites: resources/presentation-fixtures/locate_callsites/fixture.yaml
 *   read_changelogs: resources/presentation-fixtures/read_changelogs/fixture.yaml
 *   rank_verdict: resources/presentation-fixtures/rank_verdict/fixture.yaml
 * ---
 */

const { FlowOutput, loadPresentationContext, stepName } =
  await import("__ROTE_PRESENTATION_SDK__");

type StageRow = { stage: string; label: string; state: string; note: string };
type Verdict = {
  total: number; act: number; review: number; safe: number; current: number;
  headline: string; report: string; warning?: string;
};

const out = new FlowOutput();
const ctx = await loadPresentationContext();

const STAGES: Array<[string, string]> = [
  ["find_dependencies", "manifests"],
  ["resolve_versions", "registry"],
  ["locate_callsites", "call sites"],
  ["read_changelogs", "release notes"],
  ["rank_verdict", "verdict join"],
];
const STEP_HANDLES = {
  find_dependencies: ctx.step(stepName("find_dependencies")),
  resolve_versions: ctx.step(stepName("resolve_versions")),
  locate_callsites: ctx.step(stepName("locate_callsites")),
  read_changelogs: ctx.step(stepName("read_changelogs")),
  rank_verdict: ctx.step(stepName("rank_verdict")),
};

const bodyOf = (step: (typeof STEP_HANDLES)[keyof typeof STEP_HANDLES]): Record<string, unknown> | null => {
  const outcome = step.outcome;
  if (outcome.status !== "completed" && outcome.status !== "restored") return null;
  const text = (outcome.output.body as { stdout?: { text?: string } })?.stdout?.text;
  if (typeof text !== "string" || !text.trim()) return null;
  try {
    const parsed = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
};

// The ledger is not decoration. When a stage degrades -- a rate-limited
// changelog read, an unreachable registry -- the rows it fed report REVIEW
// rather than SAFE, and this is where you see why.
const ledger: StageRow[] = [];
for (const [id, label] of STAGES) {
  const step = STEP_HANDLES[id as keyof typeof STEP_HANDLES];
  const info = bodyOf(step);
  const status = step.outcome.status;
  let state: string;
  let note = "";
  if (info && (status === "completed" || status === "restored")) {
    const degraded = typeof info["warning"] === "string";
    state = degraded ? "degraded" : "ok";
    note = degraded ? String(info["warning"]) : "";
  } else if (status === "completed" || status === "restored") {
    state = "degraded";
    note = "unparseable output";
  } else if (status === "skipped" || status === "blocked") {
    state = status;
    note = String((step.outcome.output as { reason?: string }).reason ?? "");
  } else {
    state = "failed";
    note = String((step.outcome.output as { message?: string }).message ?? "").slice(0, 80);
  }
  ledger.push({ stage: id, label, state, note });
}

const GLYPH: Record<string, string> = {
  ok: "████████",
  degraded: "█████░░░",
  skipped: "░░░░░░░░",
  blocked: "░░░░░░░░",
  failed: "░░░░░░░░",
};

const fallback: Verdict = {
  total: 0, act: 0, review: 0, safe: 0, current: 0,
  headline: "no verdict",
  report: "The verdict join did not produce a report; see the stage ledger.",
};
const verdictBody = bodyOf(STEP_HANDLES.rank_verdict);
const verdict: Verdict =
  verdictBody && typeof verdictBody["report"] === "string"
    ? (verdictBody as unknown as Verdict)
    : fallback;

const okCount = ledger.filter((r) => r.state === "ok").length;
const bar = "█".repeat(Math.round((okCount / ledger.length) * 24)).padEnd(24, "░");

const lines: string[] = [];
lines.push(`UPGRADE IMPACT  ${String(ctx.params.root ?? ".")}`);
lines.push("");
lines.push(`  stages  ${bar}  ${okCount}/${ledger.length} ok`);
for (const row of ledger) {
  lines.push(`  ${GLYPH[row.state] ?? GLYPH.failed}  ${row.label.padEnd(16)}${row.state}${row.note ? ` — ${row.note}` : ""}`);
}
lines.push("");
lines.push(verdict.report);
lines.push("");
lines.push("ACT = breaking changes in code you import directly. REVIEW = you import it,");
lines.push("but the release notes could not be read, so nobody has checked. An unreadable");
lines.push("changelog is never reported as SAFE.");

out.human(lines.join("\n"));
out.summary(verdict.headline);
out.result({ run_id: ctx.run.run_id, stages: ledger, ...verdict });
