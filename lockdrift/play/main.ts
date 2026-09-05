#!/usr/bin/env -S rote play run
/**
 * Lockfile Drift
 *
 * Which dependencies would change if you installed right now.
 *
 * @rote-frontmatter
 * ---
 * name: lockfile-drift
 * version: 0.1.1
 * description: "Which of your dependencies would change if you installed right now? Your manifest declares a range, your lockfile pins a version, and your installed tree holds a third answer -- and they disagree more often than anyone checks. This reads all three off your disk and reports each dependency as DRIFT (the sources disagree in a way your next install acts on), UNLOCKED (declared, but nothing pins it), UNCHECKED (a source could not be read or observed) or SYNCED (all three read, all three agree). A source that was not read is never reported as agreement: no node_modules means the installed state was not observed, so those rows are UNCHECKED and never SYNCED. Range evaluation is deliberately narrow -- carets, tildes, exact pins and single comparators are evaluated, while unions, hyphen ranges and git, file or workspace references are reported unevaluated rather than guessed. It never installs, never resolves against a registry, and never runs a package manager, so it cannot tell you the newest version -- only whether what you already have agrees with itself. npm and Python; standard library only."
 * source: https://docs.npmjs.com/cli/v10/configuring-npm/package-lock-json
 * provenance:
 *   author: adityagaur <adityagaur12077@gmail.com>
 *   tier: local
 *   workspace: lockfile-drift
 * metadata:
 *   rote_version: "0.78.0"
 *   version: "0.1.1"
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
 *     - job-dependency-audit
 *     - job-reproducible-builds
 *     - tool-npm
 *     - tool-lockfile
 *     - effect-read-only
 * parameters:
 * - name: root
 *   param_type: string
 *   required: false
 *   default: '.'
 *   description: Path to the project to check; defaults to the current directory
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
 *   read_declared:
 *     type: process.exec
 *     timeout_ms: 60000
 *     argv:
 *     - "python3"
 *     - "@resource{read_declared.py}"
 *     - "$root"
 *   read_locked:
 *     type: process.exec
 *     timeout_ms: 60000
 *     argv:
 *     - "python3"
 *     - "@resource{read_locked.py}"
 *     - "$root"
 *   read_installed:
 *     type: process.exec
 *     timeout_ms: 90000
 *     argv:
 *     - "python3"
 *     - "@resource{read_installed.py}"
 *     - "$root"
 *   compare_pins:
 *     type: process.exec
 *     timeout_ms: 15000
 *     depends_on:
 *     - read_declared
 *     - read_locked
 *     - read_installed
 *     argv:
 *     - "python3"
 *     - "@resource{compare_pins.py}"
 *     - "--from-steps"
 *     - "@read_declared{$.stdout.text}"
 *     - "@read_locked{$.stdout.text}"
 *     - "@read_installed{$.stdout.text}"
 * ---
 */

const { FlowOutput, loadPresentationContext, stepName } =
  await import("__ROTE_PRESENTATION_SDK__");

type StageRow = { stage: string; label: string; state: string; note: string };
type Verdict = {
  total: number; drift: number; unlocked: number; unchecked: number; synced: number;
  installed_observed: boolean; headline: string; report: string; warning?: string;
};

const out = new FlowOutput();
const ctx = await loadPresentationContext();

const STAGES: Array<[string, string]> = [
  ["read_declared", "manifests"],
  ["read_locked", "lockfiles"],
  ["read_installed", "installed"],
  ["compare_pins", "comparison"],
];
const STEP_HANDLES = {
  read_declared: ctx.step(stepName("read_declared")),
  read_locked: ctx.step(stepName("read_locked")),
  read_installed: ctx.step(stepName("read_installed")),
  compare_pins: ctx.step(stepName("compare_pins")),
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
  total: 0, drift: 0, unlocked: 0, unchecked: 0, synced: 0,
  installed_observed: false,
  headline: "no comparison",
  report: "The comparison did not produce a report; see the stage ledger.",
};
const verdictBody = bodyOf(STEP_HANDLES.compare_pins);
const verdict: Verdict =
  verdictBody && typeof verdictBody["report"] === "string"
    ? (verdictBody as unknown as Verdict)
    : fallback;

const okCount = ledger.filter((r) => r.state === "ok").length;
const bar = "█".repeat(Math.round((okCount / ledger.length) * 24)).padEnd(24, "░");

const lines: string[] = [];
lines.push(`LOCKFILE DRIFT  ${String(ctx.params.root ?? ".")}`);
lines.push("");
lines.push(`  stages  ${bar}  ${okCount}/${ledger.length} ok`);
for (const row of ledger) {
  lines.push(`  ${GLYPH[row.state] ?? GLYPH.failed}  ${row.label.padEnd(16)}${row.state}${row.note ? ` — ${row.note}` : ""}`);
}
lines.push("");
lines.push(verdict.report);
lines.push("");
lines.push("DRIFT = the sources disagree in a way your next install acts on. UNCHECKED =");
lines.push("a source was not readable or not observed, so nothing is claimed about it. A");
lines.push("source that was not read is never reported as agreement.");

out.human(lines.join("\n"));
out.summary(verdict.headline);
out.result({ run_id: ctx.run.run_id, stages: ledger, ...verdict });
