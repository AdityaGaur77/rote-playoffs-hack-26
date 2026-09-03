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

## 3. Where things stand

| Phase | State |
|---|---|
| Research and Play selection | **done** |
| Analysis payload (5 scripts, 93 tests) | **done** |
| Machine setup | **done** |
| Warm-up Plays (`hello` 9/9, `dns-propagation-check` 6/6) | **done** |
| Recorded exploration (8 good captures) | **done** |
| Crystallization (`main.ts` correct and portable) | **generated — 3 rote syntax tokens left to confirm** |
| `hackathon` org membership | **BLOCKED — not a member of any org** |
| Lint, release, publish | not started |

### The blocker

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
Branch `claude/upgrade-impact-triage-publish-l2wtmk`, PR #1 (draft), head `eaab837`,
base `main` at `dd7b37b`. No CI configured, so no checks run.

```
steps/parse_manifest.py    <root>                             -> deps found in manifests
steps/fetch_registry.py    <ecosystem> <name> <current>       -> latest, repo, gap, outdated
steps/find_callsites.py    <root> <ecosystem> <name>          -> direct, hits, files, sites
steps/fetch_changelog.py   <owner/repo> <current> <latest>    -> checked, breaking, markers
steps/compute_verdict.py   [records.jsonl]                    -> tiers (stdin if no path)
tools/inline_steps.py      [--json]                           -> portable argv prefixes
tools/build_play.py        [--check]                          -> generates play/main.ts
play/main.ts               generated, 64 KB                   -> the Play
play/deps.toml                                                -> declares python3
tests/test_steps.py                                           -> 122 tests
smoke_test.sh
```

Every step after the first also has a `--batch` form taking the previous step's
output as one argv scalar. That is the chain the Play runs; see section 8.

`python3 -m pytest tests/ -q` → **118 passed, 4 skipped**. The 4 skips are opt-in live
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
| 4 | Absolute script paths | **closed** — `tools/inline_steps.py` base64-inlines each script |
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

### The three tokens still open

These are rote's own syntax and cannot be settled from this repo. They are
isolated as three constants at the top of `tools/build_play.py`:

| Constant | Current guess | What it is |
|---|---|---|
| `PARAM` | `${root}` | how a declared parameter is interpolated into a step's argv |
| `EDGE` | `@find_dependencies.stdout.text` | how one step references another's output |
| `BODY_READ` | `steps.rank_verdict.stdout.json.report` | how the presentation body reads a step's output |

`EDGE` follows the form recorded in section 9 step 2. `PARAM` and `BODY_READ`
are guesses. Confirm all three, correct the constants, re-run `build_play.py`,
and the whole 64 KB file is correct:

```bash
rote guidance play crystallization | cat
```

Faster, if it is still on the machine: read the warm-up Play that already used a
parameter — `~/.rote/flows/dns-propagation-check/main.ts` — and copy its forms
verbatim. A working example beats the reference.

`rote play lint` will catch a wrong guess before anyone sees it.

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

2. **Confirm the three tokens** in `tools/build_play.py` (see section 8), then:
   ```bash
   python3 tools/build_play.py
   ```
   Pipe `rote guidance` to `cat` — it opens a pager that will eat anything you
   paste next.

3. **Copy the Play into place and run it against the demo project.**
   ```bash
   mkdir -p ~/.rote/flows/upgrade-impact-triage
   cp play/main.ts play/deps.toml ~/.rote/flows/upgrade-impact-triage/
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts root=/home/adity/next-step-26
   ```
   Expected: numpy and scipy both ACT, headline "2 of 2 dependencies have
   breaking changes in code you actually call". **Lead the demo with scipy** —
   section 7 says why.

4. **Test the negative space.** The failure behaviours are the product:
   ```bash
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts root=/tmp/empty-dir
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts 'root=!!'
   rote play run ~/.rote/flows/upgrade-impact-triage/main.ts --resume latest root=/home/adity/next-step-26
   ```
   Empty directory should complete with "nothing to triage". Bad input should
   fail closed with dependents `BLOCKED` and a working `--resume`. Both are
   covered by tests at the script level; this checks rote propagates them.

5. **Self-check the DAG.** "1 step · 1 layer" means a monolith got written; this
   should report five steps in five layers.
   ```bash
   rote play run https://play.modiqo.ai/modiqo/play-dag play=./main.ts
   ```

6. **Release.** Lint gates release; the three-run QA, index rebuild and search
   verification are all required before the release claim is legitimate:
   ```bash
   rote play lint upgrade-impact-triage
   rote play release upgrade-impact-triage
   rote play index --rebuild
   rote play search upgrade-impact-triage
   ```

7. **Publish and read back from a clean directory** — criterion 2 is *someone
   who is not you*:
   ```bash
   rote registry play push main.ts adityagaur
   cd /tmp && rote play run https://play.modiqo.ai/adityagaur/upgrade-impact-triage root=. --yes
   ```

8. **Take the two multipliers.** A daily-habit Play that is literally scheduled
   daily demonstrates criterion 1 instead of claiming it, and publishing early
   buys a week of adoption:
   ```bash
   play recurring probe
   play recurring schedule --reference adityagaur/upgrade-impact-triage@0.1.0 \
     --cadence daily --why "Catch breaking upgrades before they land" --for 6d
   play journey view --active
   ```

9. **Re-run `build_play.py` after any change to `steps/`.** The test suite will
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
- **A process-only workspace uses plain `workspace export`.** `rote play pending write` is
  the pending-save route for *mixed* adapter/process/browser workspaces and will push you
  toward declaring an adapter you do not have.
- **`rote detect` cannot run here.** It needs an action ID, which only exists after an HTTP
  request. A pure `process.exec` workspace never creates one. Use `rote workspace health`.
- **`rote guidance` opens a pager.** Anything pasted while it is open goes into the pager,
  then gets executed as mangled commands when it exits. Always `| cat`.
- **Never paste multi-line blocks containing `#` comments or `<placeholders>`.** Both were
  mangled by bash repeatedly. One bare command per line.
- **Handles are immutable.** `adityagaur` is locked in — that was a one-shot.
- **Capture is never retrospective.** Work begun outside the workspace cannot be
  crystallized. Recorder first, every time.
- **Steps have no TTY.** Pass `--yes` to anything that might prompt.
- **In the Play body:** no literal `*/` inside the frontmatter comment (it closes the block
  early); quote non-string defaults (`default: '20'`, not `default: 20`);
  `process.stdout.write`, never `console.log`.

---

## 11. Deliberately not doing

- **`find_callsites` returns test files before source files**, so numpy's representative
  site is `tests/mocks.py:13` rather than `src/ecoslice/fem.py:7`. Ranking source above
  tests would demo better — but changing it now would mean the inlined script behaves
  differently from what was recorded, breaking the link between evidence and shipped
  behaviour. **v0.2, after publish.**
