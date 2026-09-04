# upgrade-impact-triage — handoff

Written 2026-09-03, revised the same day (sections 5, 8 and 9 changed —
problem 2 is solved and the Play is generated). Read this first if you are
picking the project up cold.

---

## 1. The goal

Modiqo **Rote Playoffs**. Every participant publishes at least one Play to the shared
`hackathon` space. **Publishing *is* submitting** — there is no deck and no form.
Deadline: **Sunday 6 September 2026, 20:00 London.**

Judged on four things:

| Criterion | What it actually asks |
|---|---|
| Daily-habit gravity | Would a reasonable person run this weekly? Daily? Reflexively? |
| It actually runs | Pulled fresh and executed live by someone who is **not you** |
| Reusability | Clean parameters, honest description, stable output |
| Adoption | Installs by fellow competitors — the scoreboard |

Organizers' framing: *"nobody will remember the hackathon that produced a clever demo.
Everybody remembers the Play they still run every morning."*

---

## 2. The Play

**`upgrade-impact-triage`** — *of my outdated dependencies, which ones have breaking
changes that touch code I actually call?*

Deliberately **not**:
- "is there a CVE" — `modiqo/dependency-vulnerability-check` already owns that lane
- "is there a newer version" — that is Dependabot

The gap between them, which is where the real work of upgrading lives. Typical output:
*3 of your 47 outdated dependencies will actually break you, here they are with line
numbers. The other 44 are safe to bump blind.*

### Tiers

| Tier | Meaning |
|---|---|
| `ACT` | Breaking changes **and** you import it directly — your problem today |
| `REVIEW` | You import it directly, but breaking status is **unknown** because notes could not be read |
| `SAFE` | Outdated but never imported directly, **or** notes were read and were clean |
| `CURRENT` | Already at the latest version |

### The honesty invariant — do not break this

`REVIEW` is load-bearing. **An unreadable changelog must never be laundered into
"safe."** A rate-limited or offline run produces *more* `REVIEW` rows; it never
produces *fewer* `ACT` rows. `breaking: false` is only meaningful when `checked: true`.

Tested exhaustively across all eight `direct` × `checked` × `breaking` combinations.
Any future change that could turn an unknown into an all-clear is a bug, not a
simplification.

### Two ideas killed on research first

1. **A Play that audits other Plays before you run them.** Already ships inside Play —
   inspection discloses credentials-by-name and declared effects on every run, and
   `play_drifted` is a first-class state-machine event. Also fails criterion 1: auditing
   is occasional, not daily.
2. **A generic "what changed in my dependencies overnight" digest.** Collides with the
   published `dependency-vulnerability-check`. Rebuilding an existing Play contradicts
   the product's own core loop — *"has someone already crystallized this?"*

---

## 0. It is published

```
https://play.modiqo.ai/adityagaur/upgrade-impact-triage@0.1.0
```

Install link: `https://play.modiqo.ai/install?play=adityagaur/upgrade-impact-triage@0.1.0`

Published 2026-09-04, public, 17,859 bytes. **Publishing is submitting**, so the
entry is in. Verified the way criterion 2 asks — resolved from that URI, installed
and run from `/tmp` by a copy that had never seen the repo:

```
ACCESS
Services           none
Writes             none declared
Authentication     none
Privileged access  process

  stages  ████████████████████████  5/5 ok

2 of 2 dependencies have breaking changes in code you actually call
  ACT  pypi  numpy  1.26 -> 2.5.2   major  14 files  tests/mocks.py:13
  ACT  pypi  scipy  1.11 -> 1.18.1  minor   2 files  src/ecoslice/fem.py:8
```

*Authentication: none* is what the decision to leave `GITHUB_TOKEN` undeclared
bought. A stranger sees no credential request at all.

### Scheduled daily — 2026-09-04

`play recurring schedule` id `30dfkq33`, active, cron `30 7 * * *` (14:30 UTC),
expires 2026-09-07, why *"Catch breaking upgrades before they land"*. Criterion
1 demonstrated rather than claimed; `play journey view --active` opens a local
map of it on 127.0.0.1.

**One caveat:** the schedule records `"cwd": null` and its argv passes no
`root`, which falls back to the parameter default `.`. Whatever directory the
scheduler runs from is what gets triaged. Check with `play recurring schedule
--help` whether parameters can be pinned; a run against a real project reads
far better than one that reports "nothing to triage".

What remains is adoption, and one note from the release output worth carrying:
**a process play under a personal handle is public but not team-runnable the way
an org play is.** If the `hackathon` invite ever lands, republishing there is
additive and better for the scoreboard.

---

## 3. Where things stand

| Phase | State |
|---|---|
| Research and Play selection | **done** |
| Analysis payload (5 scripts, 93 tests) | **done** |
| Machine setup | **done** |
| Play generated and frontmatter verified on the target machine (Python 3.14) | **done** |
| Warm-up Plays (`hello` 9/9, `dns-propagation-check` 6/6) | **done** |
| Recorded exploration (8 good captures) | **done** |
| Crystallization (`main.ts` correct and portable) | **done — generated, syntax confirmed, frontmatter parses** |
| `hackathon` org membership | **BLOCKED — not a member of any org** |
| `rote play lint` | **passes clean — zero findings** |
| **First real run** | **5/5 completed, 5 layers, 3.5s — the demo output is real** |
| Negative space (absence, hard fault, blocking) | **passes — see section 7** |
| Presentation fixtures | **done** — from `run_20260904_001502.667_0` |
| `rote play release` | **released, readiness: ready** |
| **Publish** | **DONE — `adityagaur/upgrade-impact-triage@0.1.0`, public** |
| Verified from the registry | **DONE — resolved, installed and run from `/tmp`, 5/5 ok** |
| Adoption | share the URI; the scoreboard is installs by other competitors |

### Release readiness — fixed

`rote play release` passed every gate (static, human/summary/json runtime) and
the Play is released and indexed. But:

```
warning: this released play is not ready to hand to someone else
  Blocker: `python3` is declared as required with no install candidate, so a
  recipient learns they need it and nothing about how to get it
  Fix: rote guidance shell essential   # declare an install candidate in deps.toml
```

This is criterion 4 directly — a recipient who lacks `python3` is told they need
it and nothing else. The fix is `[[tools.install]]`, one entry per manager that
can supply the tool:

```toml
[[tools]]
id = "python3"
command = "python3"
required = true
version_requirement = ">=3.8"

[[tools.install]]
manager = "brew"
package = "python@3"

[[tools.install]]
manager = "apt"
package = "python3"
```

Taken verbatim from `~/.rote/flows/modiqo/dns-propagation-check/deps.toml`,
which declares the same interpreter, so the manager and package names are known
good rather than guessed. Use `command = [...]` instead of `package` when the
install is not `<manager> install <package>`. A test now asserts every required
tool carries at least a brew and an apt candidate.

`version_requirement` is checked by probing the binary's own version flags; a
version that cannot be inferred passes as unverified rather than failing, so it
costs nothing.

Note also rote's own parting advice: **"release is not proof: run the play
against real inputs before reporting completion."**

### The org blocker

```
$ rote registry org list
ok: You are not a member of any organizations
```

Publishing to the `hackathon` space is the submission, and adoption is scored on installs
by people inside it. **Chase the invite in the Modiqo Discord.** Nothing else can fix this,
and it cannot be fixed late.

Do **not** run `rote registry org create --slug hackathon`. The CLI suggests `org create`
in its `@@next` hints, but creating an org named `hackathon` would squat the organizers'
namespace and would still not make you a member of theirs.

### How to tell when the invite has landed

There is no push notification. The same command that reports the blocker is the
one that reports the fix — poll it:

```bash
rote registry org list
```

Today: `ok: You are not a member of any organizations`. Once accepted, `hackathon`
appears in that list. That is the only signal that matters, because it is the
membership the publish step actually uses.

Two other places worth a look, in order of usefulness:

```bash
rote registry whoami          # confirms which account the CLI is authenticated as
rote play search --org hackathon
```

`whoami` matters because the invite goes to an email address and the CLI is
authenticated as an account — if the Discord message named a different address
than `adityagaur12077@gmail.com`, the invite can be accepted and `org list` still
show nothing. Check the inbox for that address too; org invites are usually a
mailed accept link, not something the CLI can accept for you.

If `org list` still reports nothing an hour before the deadline, publish anyway
under `adityagaur/upgrade-impact-triage`. A published Play outside the org still
satisfies criteria 1–3, and the URL can be dropped in Discord for adoption. An
unpublished Play satisfies none of them.

---

## 4. Environment — exact facts

| | |
|---|---|
| Host | Windows 11 + WSL2 |
| **Distro** | `Ubuntu` — **NOT** `docker-desktop`, which is the WSL default and has no git/python3/rote |
| User / home | `adity` / `/home/adity` |
| Python | 3.14 |
| rote | **0.78.0** (auto-updated from 0.77.0 mid-project) |
| Play | 0.4.82 |
| Claude Code | 2.1.258 |
| Rote account | `adityagaur12077@gmail.com` |
| **Handle** | **`adityagaur`** — already claimed, and **immutable in this release** |
| Published URI will be | `play.modiqo.ai/adityagaur/upgrade-impact-triage` |
| Orgs | none |

### Paths

```
/home/adity/rote-playoffs-hack-26                       repo clone
/home/adity/next-step-26                                demo target (EcoSlice)
/home/adity/records.jsonl                               hand-built join input
/home/adity/.rote/workspaces/upgrade-impact-triage      recorded workspace
/home/adity/.rote/flows/local-process/main.ts           first export (wrong directory)
```

If `wsl` drops you into a shell with no git/python3/rote, you are in `docker-desktop`.
Fix once with `wsl --set-default Ubuntu` from PowerShell.

---

## 5. The repo

**github.com/AdityaGaur77/rote-playoffs-hack-26**

> **Work on `claude/rote-playoffs-handoff-2q99rf`.** Everything below — `tools/`,
> `play/`, the `--batch` forms, 129 tests — is on that branch and nowhere else.
> Checking out `claude/upgrade-impact-triage-publish-l2wtmk` gets you the analysis
> payload and a repo with no `tools/build_play.py`, which fails confusingly:
> ```
> python3: can't open file '.../tools/build_play.py': [Errno 2] No such file or directory
> ```
> ```bash
> git checkout claude/rote-playoffs-handoff-2q99rf && git pull
> python3 -m pytest tests/ -q          # 125 passed, 4 skipped
> ```

| Branch | Contains | PR |
|---|---|---|
| `claude/rote-playoffs-handoff-2q99rf` | **the Play** — `play/`, `tools/build_play.py`, `--batch` chain, this doc | #2 → the publish branch |
| `claude/upgrade-impact-triage-publish-l2wtmk` | analysis payload only, 89 tests | #1 → `main` |
| `main` | `dd7b37b` | — |

Both PRs are drafts and no CI is configured, so no checks run. Merging #2 into the
publish branch would collapse the two into one and remove this trap entirely.

```
steps/parse_manifest.py    <root>                             -> deps found in manifests
steps/fetch_registry.py    <ecosystem> <name> <current>       -> latest, repo, gap, outdated
steps/find_callsites.py    <root> <ecosystem> <name>          -> direct, hits, files, sites
steps/fetch_changelog.py   <owner/repo> <current> <latest>    -> checked, breaking, markers
steps/compute_verdict.py   [records.jsonl]                    -> tiers (stdin if no path)
tools/build_play.py        [--check]                          -> generates the Play
tools/make_fixtures.py     <input.json>                       -> presentation fixtures
play/main.ts               generated, 7 KB                    -> the Play
play/resources/*.py        published copies of steps/         -> named by @resource{}
play/deps.toml                                                -> declares python3
tests/test_steps.py                                           -> 137 tests
smoke_test.sh
```

Every step after the first also has a `--batch` form taking the previous step's
output as one argv scalar. That is the chain the Play runs; see section 8.

`python3 -m pytest tests/ -q` → **133 passed, 4 skipped**. The 4 skips are opt-in live
registry reads; enable with `ROTE_NET_TESTS=1`.

### Contracts every step honours

- **Every remote problem is an expected absence** → `ok: true`, exit 0, with a `warning`.
  A broken *invocation* fails closed with exit 2.
- **Collections are packed into delimited scalars**, never JSON — `chr(31)` between fields,
  `chr(30)` between rows. This is deliberate: rote value-edges must resolve to a scalar.
- **stdlib only** — `json`, `os`, `re`, `sys`, `time`, `urllib`. Nothing third-party.
  `python3` is the entire dependency, which is the adoption argument: zero preflight
  blockers on any machine that installed rote.

### Environment variables

- `GITHUB_TOKEN` — optional, raises the GitHub rate limit from 60/hr to 5000/hr.
  Deliberately optional so `rote play inspect` shows *Authentication: none*.
- `GITHUB_API_BASE` — overrides the API root (default `https://api.github.com`).
  Exists for GitHub Enterprise and for the hermetic stub-server tests.

---

## 6. Bugs found and fixed — keep these fixed

Each would have shipped silently.

| # | Bug | Why it mattered |
|---|---|---|
| 1 | crates.io 403s without a `User-Agent` | The entire Rust path would have failed |
| 2 | PyPI `project_urls` keys vary in case | numpy publishes `source`, others `Source Code` — dropped the repo for common packages |
| 3 | Repo URL took the last two path segments | `github.com/numpy/numpy/issues` resolved to non-existent `numpy/issues` |
| 4 | Malformed manifest reported "no manifest found" | Swallowed the parse error; a degraded source must be a visible unknown |
| 5 | `^\s*` under `re.M` matched across newlines | Python import line numbers pointed at blank lines — call-site accuracy is the whole promise |
| 6 | Commented-out `require()` counted as a call site | Inflated the very count the Play exists to shrink |
| 7 | `re.split` used positional `maxsplit` | Deprecated in Python 3.13+; target is 3.14 |
| 8 | `fetch_changelog` success path untested | GitHub was unreachable from the authoring container. Fixed with `GITHUB_API_BASE` + a localhost stub server, 8 tests |
| 9 | Bug 5 **survived in `fetch_changelog`** | Matches began on blank lines, so quoted samples came back empty |
| 10 | Prereleases double-counted | `v2.4.0` and `v2.4.0rc1` reported identical findings. **Worse: the 12-sample cap filled with rc duplicates, so the v2.0.0 major-bump evidence never appeared in the output at all** |
| 11 | `compute_verdict` was stdin-only | Awkward to capture. Now takes a JSONL path, falls back to stdin, and fails closed (exit 2) on an unreadable named file |

Bug 10 is the cautionary tale: it looked cosmetic and was actually hiding the headline.

---

## 7. The recorded exploration

Workspace `upgrade-impact-triage`. **A workspace is active because you are standing in
its directory** — there is no `workspace use` verb:

```bash
eval $(rote cd upgrade-impact-triage)
```

### Captures

| ID | Command | Result |
|---|---|---|
| `@1` | `parse_manifest /home/adity/next-step-26` | count 2 — numpy 1.26, scipy 1.11, from `pyproject.toml` |
| `@2` | `fetch_registry pypi numpy 1.26` | latest 2.5.2, repo `numpy/numpy`, gap **major** |
| `@3` | `fetch_registry pypi scipy 1.11` | latest 1.18.1, repo `scipy/scipy`, gap **minor** |
| `@4` | `find_callsites … pypi numpy` | direct true, **14 files** of 23 scanned, first `tests/mocks.py:13` |
| `@5` | `find_callsites … pypi scipy` | direct true, **2 files**, first `src/ecoslice/fem.py:8` |
| `@6` | `fetch_changelog numpy/numpy 1.26 2.5.2` | checked true, breaking true, 34 releases |
| `@7` | **JUNK** — `compute_verdict` run before pulling the records-file commit | read stdin, got nothing, said "nothing to triage" |
| `@8` | `fetch_changelog scipy/scipy 1.11 1.18.1` | checked true, breaking true, 21 releases |
| `@9` | **JUNK** — exact duplicate of `@8` | |
| `@10` | **SUPERSEDED** — `compute_verdict` without `first_site` | |
| `@11` | `compute_verdict /home/adity/records.jsonl` | **the good one** |

**Good captures: `@1 @2 @3 @4 @5 @6 @8 @11`. Junk: `@7 @9 @10`.**

### The findings — this is the demo

```
numpy  1.26  -> 2.5.2   major   14 files   breaking-change, incompatible, no-longer, removal, rename
scipy  1.11  -> 1.18.1  minor    2 files   incompatible, migration-guide, no-longer, rename
```

`@11` headline: **"2 of 2 dependencies have breaking changes in code you actually call"**

### The negative space, run against the real Play — 2026-09-04

The failure behaviours are the product, and `rote guidance play testing` asks
for exactly these.

**Expected absence** (`root=/tmp/empty-dir`) — completes, and says so explicitly
in both the human output and the ledger rather than fabricating a default:

```
  stages  ░░░░░░░░░░░░░░░░░░░░░░░░  0/5 ok
  █████░░░  manifests       degraded — no supported manifest found under /tmp/empty-dir
  █████░░░  registry        degraded — no dependencies on input
  █████░░░  call sites      degraded — no dependencies on input
  █████░░░  release notes   degraded — no dependencies on input
  █████░░░  verdict join    degraded — no dependency records on input

nothing to triage
```

**Hard fault** (`root=/nope/does/not/exist`) — fails rather than rendering a
degraded-looking success, and every dependent is blocked for a stated reason:

```
  find_dependencies  FAILED (@11 exit 2; parse_manifest: root is not a directory: ...)
  resolve_versions   BLOCKED (upstream failed)
  ...
  Summary: 0/5 completed, 1 failed, 4 blocked
  Retry: rerun this play with --resume run_20260904_001658.861_10
error: 1 step(s) failed.
```

That is the fail-closed path holding end to end: an unreadable input produces a
failure, never a silent all-clear. Note the presentation still rendered — the
ledger reports `failed` and `blocked` rather than an empty success.

**Recovery** — `--resume` was exercised and completed 5/5, but against a
different `root` than the failed run, so it started fresh rather than reusing
work. Reuse itself is still unproven. To test it properly, fail a *later* step
and resume that same run id.

### The Play produced it for real — 2026-09-04

`rote play run ... root=/home/adity/next-step-26`, run_id `run_20260904_001502.667_0`:

```
  [layer 1]  find_dependencies  @1  (30ms)
  [layer 2]  resolve_versions   @2  (668ms)
  [layer 3]  locate_callsites   @3  (51ms)
  [layer 4]  read_changelogs    @4  (2.6s)
  [layer 5]  rank_verdict       @5  (30ms)
  Summary: 5/5 completed, 0 failed, 0 blocked   Duration: 3.5s

  stages  ████████████████████████  5/5 ok

2 of 2 dependencies have breaking changes in code you actually call

  ACT     pypi   numpy  1.26 -> 2.5.2   major  14 files  tests/mocks.py:13
          breaking-change,incompatible,no-longer,removal,rename
  ACT     pypi   scipy  1.11 -> 1.18.1  minor   2 files  src/ecoslice/fem.py:8
          incompatible,migration-guide,no-longer,rename
```

Five steps in five layers, so the DAG is a real graph and not a monolith. Every
piece of rote syntax that could have been wrong is now confirmed by execution
rather than by inference: `$root`, `@step{...}` edges, `@resource{}`, the
presentation SDK body, and the stage ledger.

**scipy is the story.** It is a *minor* bump — the kind everyone bumps blind, and the kind
Dependabot reports as routine. But v1.14, v1.15, v1.16, v1.17 and v1.18 each carry
"Backwards incompatible changes", plus a sparse-array migration guide, and the project
imports `scipy.sparse as sp` in exactly two files: `src/ecoslice/fem.py:8` and
`plugin/ecoslice_core.py:23`. numpy's `ACT` is the obvious one. **scipy is the one that
would have shipped.** Lead the demo with it.

### records.jsonl (hand-built — see problem 2 below)

```
{"ecosystem":"pypi","name":"numpy","current":"1.26","latest":"2.5.2","gap":"major","outdated":true,"direct":true,"files":14,"checked":true,"breaking":true,"first_site":"tests/mocks.py:13"}
{"ecosystem":"pypi","name":"scipy","current":"1.11","latest":"1.18.1","gap":"minor","outdated":true,"direct":true,"files":2,"checked":true,"breaking":true,"first_site":"src/ecoslice/fem.py:8"}
```

---

## 8. The export, and where the six problems went

The first export (`rote workspace export main.ts --params root`) wrote
`/home/adity/.rote/flows/local-process/main.ts` and had six problems. Five are
now closed in code; one is a question only the local rote install can answer.

| # | Problem | State |
|---|---|---|
| 1 | `root` declared but never used; steps hardcoded `/home/adity/next-step-26` | **closed** — `root` is threaded into the two steps that take a path |
| 2 | `/home/adity/records.jsonl` produced by no step | **closed** — see below |
| 3 | Steps named `python3`, `python3_2` … `python3_9` | **closed** — `find_dependencies`, `resolve_versions`, `locate_callsites`, `read_changelogs`, `rank_verdict` |
| 4 | Absolute script paths | **closed** — the scripts are embedded in the frontmatter as source |
| 5 | `description: ""` | **closed** — written, and asserted non-empty by a test |
| 6 | Junk steps `@7`, `@9`, `@10` came through | **closed** — the Play is generated from a declared graph, not re-exported from the workspace |

**Do not hand-edit `play/main.ts`.** It carries ~59 KB of base64, so a step fixed
in `steps/` but not regenerated ships a Play that does something else.
`python3 tools/build_play.py` writes it; `--check` fails if it is stale, and the
test suite runs `--check`, so a stale Play is a test failure rather than a
published surprise.

### How problem 2 was solved

`compute_verdict` read a records file that no step produced and that no
stranger's machine has. The fix was not to add a step that writes the file —
it was to remove the file.

Every stage after the first now has a `--batch` form that takes the previous
stage's stdout as **one argv scalar**:

```
find_dependencies   parse_manifest   <root>
resolve_versions    fetch_registry   --batch <upstream>
locate_callsites    find_callsites   --batch <root> <upstream>
read_changelogs     fetch_changelog  --batch <upstream>
rank_verdict        compute_verdict  --batch <upstream>
```

Stages share one 13-column carrier record. Each fills its own columns and passes
the rest through, so nothing has to exist on disk and no stage needs to know how
many dependencies there are — it works on any repository, not just the one it was
recorded against.

| Cols | Filled by | Fields |
|---|---|---|
| 0–2 | `parse_manifest` | ecosystem, name, current |
| 3–6 | `fetch_registry` | latest, repo, gap, outdated |
| 7–9 | `find_callsites` | direct, files, first_site |
| 10–12 | `fetch_changelog` | checked, breaking, markers |

**The honesty invariant, applied to the pipeline itself.** Carrier booleans are
`"1"` / `"0"` when known and `""` when the stage that fills them has not run.
That third state is load-bearing: an unfilled column reads as UNKNOWN, never as
a clean bill of health. Skip the registry stage and every row reports REVIEW
rather than CURRENT. Skip the call-site stage and they report REVIEW rather than
SAFE. **A stage that did not run can only widen REVIEW.** Six tests hold this
down; do not "simplify" them away.

The single-package forms are untouched, so captures `@1`–`@8` still describe
what the scripts do.

A stage accepts either a whole upstream payload or a bare `packed` scalar, so
the steps do not depend on whether the value edge resolves `.stdout.text` or
`.stdout.json.packed`. That was deliberate: it decouples the Python from the one
question still open.

### The syntax, confirmed

Settled against `~/.rote/flows/modiqo/dns-propagation-check/main.ts` — a
released Play by the Modiqo CEO, and a better reference than the guidance text
because it is known to run. Note the path: installed Plays live under
`flows/<publisher>/<name>/`, not `flows/<name>/`.

| | Form | Note |
|---|---|---|
| Parameter | `$root` | a bare `$name`, **not** `${name}` |
| Value edge | `@step{$.stdout.text \| fromjson \| .packed}` | `@step{...}` wrapping a jq expression over the step outcome |
| Resource | `@resource{parse_manifest.py}` | a file published under `resources/` |
| Body | `loadPresentationContext()` + `ctx.step(stepName("..."))` | see below |

Two of the three earlier guesses were wrong, which is why they were isolated in
one file rather than spread through a 64 KB document.

### Steps are published files, not an argv payload

`rote play lint` rejected both earlier designs:

```
STEP_INLINE_CODE_PAYLOAD: argv[2] contains a line break and has 5343
characters, above the 256-character inline limit. Keep `process.exec` argv as
command structure: move static, non-secret, redistributable code under
`resources/` and invoke it with a literal `@resource{...}` token.
```

Base64 and literal source both smuggle a program into argv, and argv is command
structure. The mechanism rote wants is a published file:

```
play/
  main.ts            7 KB, not 64 KB
  deps.toml
  resources/
    parse_manifest.py  fetch_registry.py  find_callsites.py
    fetch_changelog.py compute_verdict.py
```

```yaml
argv:
- "python3"
- "@resource{parse_manifest.py}"
- "$root"
```

This is better than either thing it replaced. argv reads as a command, and the
steps are ordinary Python files a judge can read before running them — which is
most of what "honest description" means when the thing described is a program.

`tools/inline_steps.py` is deleted. No inlining mode can pass a 256-character
limit, so keeping it would only have suggested a wrong answer.

`build_play.py` writes `main.ts` and `resources/`, and `--check` fails if either
has drifted from `steps/`. Three tests assert each published resource is
byte-identical to the script the suite exercises, that the published copy still
fails closed on an unreadable input, and that no argv element carries a line
break or exceeds 256 characters — the rule that caught two designs is now a
test rather than a lesson.

### deps.toml has a schema, and it is not `[deps]`

```
unknown field `deps`, expected one of `schema_version`, `tools`, `files`, `readiness`
```

The shape lint printed:

```toml
schema_version = 1

[[tools]]
id = "python3"
command = "python3"
required = true
version_requirement = ">=3.8"
```

`GITHUB_TOKEN` stays undeclared on purpose — it is optional, and leaving it out
is what keeps `rote play inspect` reporting *Authentication: none*.

### The body is the presentation SDK, not process.stdout.write

```ts
const { FlowOutput, loadPresentationContext, stepName } =
  await import("__ROTE_PRESENTATION_SDK__");
const out = new FlowOutput();
const ctx = await loadPresentationContext();
const step = ctx.step(stepName("rank_verdict"));
```

`step.outcome.status` is `completed` / `restored` / `skipped` / `blocked` /
failed, and the payload is `outcome.output.body.stdout.text` — a string to be
`JSON.parse`d. Output goes through `out.human()`, `out.summary()` and
`out.result()`.

Our body builds the same stage ledger the reference does. That is not
decoration: when a stage degrades, the rows it fed report REVIEW rather than
SAFE, and the ledger is where you see which stage and why.

### `root` is now optional, defaulting to `.`

The reference makes every parameter optional with a default, and it is the
better call for adoption: `rote play run <url>` with no arguments triages the
directory you are standing in. A Play that needs an argument is a chore; one
that runs bare is a habit.

### Presentation lives in Python, not TypeScript

`compute_verdict` emits a `report` field: the finished plain-text table. The
Play body has one job — print that string. The formatting is therefore covered
by the same test suite as the ranking it presents, and the amount of unverified
TypeScript in the Play is two lines.

---

## 9. What to do next, in order

1. **Discord — the `hackathon` org invite.** Handle `adityagaur`, account
   `adityagaur12077@gmail.com`. The message is posted; section 3 says how to
   tell when it lands. Everything below proceeds in parallel; only step 8 is
   gated on it.

2. **Build the Play.** The syntax is settled; this just writes the file.
   ```bash
   python3 tools/build_play.py
   ```
   It refuses to write a Play whose frontmatter does not parse, so a clean run
   is already a check. If `rote play lint` still objects to something in the
   embedded source, `python3 tools/build_play.py --base64` falls back to the
   opaque form.

3. **Copy the Play into place and run it against the demo project.** Address it by path, not
   by name, until the stale `local-process` export is out of `~/.rote/flows/` — see section 10.
   ```bash
   mkdir -p ~/.rote/flows/upgrade-impact-triage
   cp -r play/main.ts play/deps.toml play/resources ~/.rote/flows/upgrade-impact-triage/
   rote play lint ~/.rote/flows/upgrade-impact-triage/main.ts
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts root=/home/adity/next-step-26
   ```
   Expected: numpy and scipy both ACT, headline "2 of 2 dependencies have
   breaking changes in code you actually call". **Lead the demo with scipy** —
   section 7 says why.

4. **Presentation fixtures — done.** Lint reports zero findings with them in
   place. Rebuild only if a step's output shape changes; `presentation_fixtures:`
   feeds quality scoring, and the evidence must come from a real run because
   lint will not fabricate a process body.

   The durable input lives under the **DAG workspace**, not `~/.rote/` and not
   the repo:
   ```bash
   find ~/.rote/workspaces -type f -name input.json -path '*presentation*'
   ```
   Pick a run where all five steps completed, then:
   ```bash
   python3 tools/make_fixtures.py ~/.rote/workspaces/dag-upgrade-impact-triage-4f8ffc5f/.rote/presentation/run_20260904_001502.667_0/input.json
   python3 tools/build_play.py
   ```
   `make_fixtures.py` packages **only** stdout and stderr. The recorded body
   also carries cwd, invocation, artifact paths and environment, and a test
   plants a fake token in each of those to prove none of it reaches the Play.
   `build_play.py` declares the map only once the files exist, because a
   declaration with a missing target is a lint error.

   The shape, from `rote grammar steps`:
   ```yaml
   presentation_fixtures:
     rank_verdict: resources/presentation-fixtures/rank_verdict/fixture.yaml
   ```
   ```yaml
   schema_version: 1
   kind: process.exec
   status:
     exit: { kind: code, code: 0 }
     duration_ms: 30
     timeout_ms: 15000
   stdout: resources/presentation-fixtures/rank_verdict/stdout.json
   stderr: resources/presentation-fixtures/rank_verdict/stderr.txt
   ```
   Fixtures participate in package identity, so lint again before release.

5. **Test the negative space.** The failure behaviours are the product:
   ```bash
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts root=/tmp/empty-dir
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts 'root=!!'
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts --resume latest root=/home/adity/next-step-26
   ```
   Empty directory should complete with "nothing to triage". Bad input should
   fail closed with dependents `BLOCKED` and a working `--resume`. Both are
   covered by tests at the script level; this checks rote propagates them.

6. **Self-check the DAG.** "1 step · 1 layer" means a monolith got written; this
   should report five steps in five layers.
   ```bash
   rote play run https://play.modiqo.ai/modiqo/play-dag play=./main.ts
   ```

7. **Release.** Lint gates release; the three-run QA, index rebuild and search
   verification are all required before the release claim is legitimate:
   ```bash
   rote play lint upgrade-impact-triage
   rote play release upgrade-impact-triage
   rote play index --rebuild
   rote play search upgrade-impact-triage
   ```

8. **Publish and read back from a clean directory** — criterion 2 is *someone
   who is not you*:
   ```bash
   rote registry play push main.ts adityagaur
   cd /tmp && rote play run https://play.modiqo.ai/adityagaur/upgrade-impact-triage root=. --yes
   ```

9. **Take the two multipliers.** A daily-habit Play that is literally scheduled
   daily demonstrates criterion 1 instead of claiming it, and publishing early
   buys a week of adoption:
   ```bash
   play recurring probe
   play recurring schedule --reference adityagaur/upgrade-impact-triage@0.1.0 \
     --cadence daily --why "Catch breaking upgrades before they land" --for 6d
   play journey view --active
   ```

10. **Re-run `build_play.py` after any change to `steps/`.** The test suite will
   tell you, but only if you run it.

---

## 10. Gotchas that cost real time

- **`docker-desktop` is the default WSL distro.** A plain `wsl` lands in a BusyBox image
  with no git, python3 or rote, and `/root` empty. It looks exactly like a wiped machine.
  `wsl -d Ubuntu`, or `wsl --set-default Ubuntu` once.
- **A workspace is active because you are `cd`'d into it.** `eval $(rote cd <name>)`.
  There is no `workspace use` / `activate` / `switch` verb, and `rote proc run` outside a
  workspace directory captures nothing.
- **`rote workspace export <output>` takes a file path, and its directory names the flow.**
  Passing a bare `main.ts` produced a flow called `local-process`.
- **A flow's *name* comes from its frontmatter, not its directory**, so the stale `local-process`
  export claimed `upgrade-impact-triage` too and every command that takes a name became
  ambiguous:
  ```
  error: flow reference `upgrade-impact-triage` is ambiguous — 2 flows match
  ```
  `rote play lint|run` also accept a **file path**, which is the way through without touching
  anything. To clear it for good, move the stale export out of `~/.rote/flows/` and
  `rote play index --rebuild`. Deleting is not necessary and the old export is the only copy of
  what section 8 describes.
- **A process-only workspace uses plain `workspace export`.** `rote play pending write` is
  the pending-save route for *mixed* adapter/process/browser workspaces and will push you
  toward declaring an adapter you do not have.
- **`rote detect` cannot run here.** It needs an action ID, which only exists after an HTTP
  request. A pure `process.exec` workspace never creates one. Use `rote workspace health`.
- **`rote grammar steps` is the authority on step syntax** — `depends_on`, `$param`, `@step{…}`,
  `for_each` fan-out, conditions, concurrency, timeouts — and on the `presentation_fixtures:` map.
  `rote guidance typescript play-creation` owns the presentation body and the `FlowOutput`
  contract. Reach for those before inferring anything.
- **`rote guidance` opens a pager.** Anything pasted while it is open goes into the pager,
  then gets executed as mangled commands when it exits. Always `| cat`.
- **Never paste multi-line blocks containing `#` comments or `<placeholders>`.** Both were
  mangled by bash repeatedly. One bare command per line.
- **Set `git config user.name` / `user.email` before the first commit.** Without them `git commit`
  aborts with "empty ident name", and the next `git pull --rebase` blames uncommitted changes
  instead — two confusing errors from one missing setting.
- **GitHub has not accepted passwords for git since 2021.** Use a Personal Access Token in the
  password field; the account password always fails with "Password authentication is not
  supported". The username is bare `AdityaGaur77` — a leading space or `@` shows up
  URL-encoded as `%20%40` and fails before the token is even checked.
- **Never paste a Play's own output back into the shell.** The report contains `->`, which bash
  reads as a redirect: pasting the ACT rows created files named `2.5.2` and `1.18.1` in the repo
  root. `git rm` them if they got committed.
- **Handles are immutable.** `adityagaur` is locked in — that was a one-shot.
- **Capture is never retrospective.** Work begun outside the workspace cannot be
  crystallized. Recorder first, every time.
- **Steps have no TTY.** Pass `--yes` to anything that might prompt.
- **In the Play body:** no literal `*/` inside the frontmatter comment (it closes the block
  early); quote non-string defaults (`default: '20'`, not `default: 20`). Output goes through
  the presentation SDK — `out.human()` / `out.summary()` / `out.result()` — **not**
  `process.stdout.write` and not `console.log`.
- **Installed Plays live under `~/.rote/flows/<publisher>/<name>/`**, not `flows/<name>/`.
  `modiqo/dns-propagation-check` is the best syntax reference on the machine; read it before
  guessing at anything.
- **Parameters are `$name`, not `${name}`.** Value edges are `@step{<jq>}`, and the jq runs over
  the step outcome, so a field is `@step{$.stdout.text | fromjson | .packed}`.

---

## 11. Deliberately not doing

- **`find_callsites` returns test files before source files**, so numpy's representative
  site is `tests/mocks.py:13` rather than `src/ecoslice/fem.py:7`. Ranking source above
  tests would demo better — but changing it now would mean the inlined script behaves
  differently from what was recorded, breaking the link between evidence and shipped
  behaviour. **v0.2, after publish.**
