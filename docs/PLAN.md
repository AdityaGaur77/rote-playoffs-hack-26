# Build plan

## Why this Play

Judging (from `docs/playoffs/ANNOUNCEMENT.md` in `modiqo/play`): **daily-habit gravity**,
**it actually runs** (pulled fresh and executed by someone who is not you), **reusability**,
and **adoption** (installs by fellow competitors count).

Two earlier candidates were discarded:

- **A Play that audits other Plays before running them.** Already ships inside Play itself —
  inspection discloses credentials-by-name and declared effects before every run, and
  `play_drifted` is a first-class state-machine event. It also fails the first criterion: an audit
  tool is an occasional utility, not a daily habit.
- **A generic "what changed in my dependencies overnight" digest.** Collides with the published
  exemplar `modiqo/dependency-vulnerability-check` (lockfiles vs. the OSV database, 10 steps ×
  5 layers). Rebuilding an existing Play contradicts the product's own core loop — *"has someone
  already crystallized this?"* — and judges would spot it immediately.

`upgrade-impact-triage` sits in the gap neither covers, and has genuine daily gravity: developers
avoid upgrades precisely because working out which are risky is expensive by hand.

## Why it fits the architecture

- **Parallel by construction.** One reading per dependency → `for_each: '$.deps'` with
  `max_concurrency: 4`. Root steps fan out; the join computes impact. The same shape as
  `dns-propagation-check`: validate → parallel probes → verdict-join.
- **Lightest-first, so zero setup for adopters.** npm, PyPI, crates.io and GitHub releases are all
  public JSON, so every step is `process.exec` — no adapter, no credentials, no declared writes.
  The docs cite `whale-flow-monitor` dropping its adapters for direct REST as a win.
- **Degrade, never die.** A package with no changelog is a labeled `degraded` row, not a crash.
- **One clean parameter:** `root=.`

## Remaining work

1. Install rote — see [SETUP.md](SETUP.md). Nothing below can start until this is done.
2. `rote init upgrade-impact-triage --seq`
3. Explore **in the shape of the Play**: one capture per reading, never a mega-command. Parse
   manifest → `@1`. Registry metadata per dependency → `@2`, `@3`… Changelog → `@N`. Call sites →
   `@N`. Join → verdict. Use `rote query schema @N` rather than guessing response shapes.
4. `rote play pending write` to anchor, then `rote workspace export … --params root`
5. `rote play lint main.ts` — fix what it names
6. Test the negative space: a package that does not exist, a project with no manifest, a
   dependency with no changelog. Verify labeled degraded rows and a working `--resume`.
7. Self-x-ray: `rote play run https://play.modiqo.ai/modiqo/play-dag play=./main.ts`. If it reports
   `1 step · 1 layer`, the structure was hidden inside one script — rewrite.
8. `rote play release` → `rote registry play push main.ts <owner>` → canonical readback: run the
   published URI from `/tmp`.

**Capture is never retrospective.** `$play explore <outcome>` is the entrance and a healthy session
auto-advances to save/test/publish; `$play settle <cap>` is a recovery door, not the main path.
Work begun outside the lifecycle cannot be crystallized — open the recorder *first*.

## Authoring rules that will bite

- Value-edge jq must resolve to a **scalar**. Pack collections into a delimited scalar with
  `chr(31)` / `chr(30)` separators and unpack in the consumer. No `tojson`.
- No literal `*/` anywhere inside the frontmatter JSDoc comment — it closes the block early.
- `parameters:` use `param_type`; quote non-string defaults (`default: '20'`).
- Explicit `timeout_ms` per step (~15s local, 45–90s network). The 30s default is a decision you
  did not make.
- Steps have no TTY — pass `--yes` to any subcommand that might prompt.
- Presentation: `stepName("literal")` only; call all three of `out.human` / `out.summary` /
  `out.result`; declare `representations`.
- `process.stdout.write(...)`, never `console.log` (→ `FLOW_OUTPUT_BARE_CONSOLE_LOG`).

## Two multipliers

- **Make it recur.** `play recurring probe`, then `play recurring schedule --reference
  <owner>/upgrade-impact-triage@<ver> --cadence daily --why "…" --for 6d`. A daily-habit Play that
  is literally scheduled daily demonstrates the first criterion rather than claiming it.
- **Record the journey.** `play journey view --active`, keep one wrong turn and its correction in
  the clip, post with `#RotePlayoffs`.

## Prior art worth reading first

`modiqo/dependency-vulnerability-check` (per-ecosystem fan-out, staged resume),
`modiqo/dns-propagation-check` (validate → parallel probes → verdict-join),
`modiqo/hello` (9 steps × 2 layers), `modiqo/play-dag` (x-ray any DAG).
