# upgrade-impact-triage

A [Rote](https://github.com/modiqo/rote-releases) Play for the **Rote Playoffs** hackathon
(1–6 September 2026), answering the question dependency tooling skips:

> Of my outdated dependencies, which ones have breaking changes that touch code I actually call?

Not *"is there a CVE"* — that is the already-published `modiqo/dependency-vulnerability-check`.
Not *"is there a newer version"* — that is Dependabot. The gap in between, which is where the
actual work of upgrading lives.

Typical output shape: **3 of your 47 outdated dependencies have breaking changes in code you
really use — here they are, with line numbers.** The other 44 are safe to bump blind.

## The ranking, which is the whole point

| Tier | Meaning |
|---|---|
| `ACT` | Breaking changes **and** you import it directly — your problem today |
| `REVIEW` | You import it directly, but breaking status is **unknown** because notes could not be read |
| `SAFE` | Outdated but never imported directly, or notes were read and were clean |
| `CURRENT` | Already at the latest version |

**`REVIEW` is load-bearing.** An unreadable changelog must never be laundered into "safe" — that
would tell someone an upgrade is fine when nobody checked. A rate-limited run produces *more*
`REVIEW` rows; it never produces *fewer* `ACT` rows. The invariant is tested exhaustively across
all eight `direct` × `checked` × `breaking` combinations.

## Steps

Each script is one rote step. A Play is not hand-authored — it is compiled from an execution
trace — so these are the payload that runs inside the steps, built and tested ahead of the
recorded exploration so the trace comes out in the right shape.

| Script | Role |
|---|---|
| `steps/parse_manifest.py <root>` | Walk a project; parse `package.json` / `pyproject.toml` / `requirements.txt` / `Cargo.toml` into one flat deduplicated list |
| `steps/fetch_registry.py <eco> <name> [current]` | One dependency, one registry reading: latest version, major/minor/patch gap, GitHub source repo |
| `steps/fetch_changelog.py <owner/repo> <cur> <latest>` | Read release notes in the version range and judge them breaking |
| `steps/find_callsites.py <root> <eco> <name>` | Is it imported directly, and where — the step that separates this from Dependabot |
| `steps/compute_verdict.py [records.jsonl]` | Join everything into the ranked verdict and render the report |

Each of the four later scripts also has a `--batch` form that takes the *previous step's output*
as one argv scalar, so the Play runs as a chain with nothing on disk between steps:

```
parse_manifest <root>
  -> fetch_registry  --batch <upstream>
  -> find_callsites  --batch <root> <upstream>
  -> fetch_changelog --batch <upstream>
  -> compute_verdict --batch <upstream>
```

The single-package forms are unchanged; `--batch` is what makes the Play portable.

### Step contract

| Situation | Behaviour |
|---|---|
| Expected absence (unknown package, flaky registry, no changelog) | `{"ok": true, "warning": ...}` on stdout, **exit 0** — a labeled degraded row |
| Hard fault (bad invocation, unreadable root) | message on **stderr**, **exit 2** — dependents BLOCKED, `--resume` offered |

stdout is data, exit status is the failure signal. Collections cross step boundaries as a
delimited scalar (`chr(31)` fields, `chr(30)` records) because value-edge jq must resolve to a
scalar. Standard library only, so `deps.toml` declares `python3` and nothing else — no adapter,
no credentials, no declared writes, so a stranger runs it in one command.

### The carrier record

`--batch` stages share one 13-column record. Each fills its own columns and passes the rest
through:

| Cols | Filled by | Fields |
|---|---|---|
| 0–2 | `parse_manifest` | ecosystem, name, current |
| 3–6 | `fetch_registry` | latest, repo, gap, outdated |
| 7–9 | `find_callsites` | direct, files, first_site |
| 10–12 | `fetch_changelog` | checked, breaking, markers |

Booleans are `"1"` / `"0"` when known and **`""` when the stage that fills them has not run**.
That third state is load-bearing and it is the honesty invariant applied to the pipeline itself: an
unfilled column reads as UNKNOWN, never as a clean bill of health. Skip the registry stage and
every row reports REVIEW rather than CURRENT; skip the call-site stage and they report REVIEW
rather than SAFE. A stage that did not run can only widen REVIEW.

A stage accepts either a whole upstream payload or a bare `packed` scalar, so the steps do not
depend on whether the value edge resolves `.stdout.text` or `.stdout.json.packed`.

## Try it

```bash
./smoke_test.sh /path/to/some/project
```

`smoke_test.sh` is **local verification only, not the exploration path.** Running one script that
does everything would make rote record a single opaque step with no edges — nothing to
parallelize, checkpoint, resume, or blame per source. During the recorded exploration each
reading gets its own `rote proc run` capture, so independent readings become parallel root steps.

## Picking this up cold

`docs/HANDOFF.md` is the full state of the project: the goal, what is done, the four
remaining problems with the exported play, the exact next steps, and the gotchas that
cost time. Read it before touching anything.

## Tests

```bash
python3 -m pytest tests/ -q                    # hermetic
ROTE_NET_TESTS=1 python3 -m pytest tests/ -q   # plus live npm / PyPI / crates.io reads
```

122 tests — 118 passing, 4 skipped by default. Coverage includes the honesty invariant above, exact call-site line
numbers, comment filtering, vendor-directory exclusion, and the negative space — unknown package,
unsupported ecosystem, empty directory, malformed manifest, empty stdin, bad invocation.

Release candidates are dropped when the same version also shipped a final release, since their
notes are duplicates — unless prereleases are the only releases in range, where they are the only
evidence there is.

The GitHub release-notes reader is exercised end to end against a stub API served on localhost
(`GITHUB_API_BASE`), so the path that actually reads notes — samples, markers, draft filtering,
range selection, 404, rate limit, 500 — is covered without a network or a rate-limit budget.

## Publishing: the scripts travel with the Play

A recorded capture bakes in the absolute path it ran from, which exists on exactly one machine.
`tools/inline_steps.py` emits a self-contained `python3 -c` argv prefix per step, so the exported
`main.ts` carries the scripts instead of pointing at them:

```bash
python3 tools/inline_steps.py --json
```

Base64 keeps the encoded body free of quotes and shell metacharacters, and arguments still land in
`sys.argv[1:]` exactly as they do when the file is run directly — no step script changes. Tests
assert the inlined and file forms produce identical output and identical exit codes, including the
fail-closed path.

## The Play itself

`play/main.ts` is **generated, never hand-edited** — it carries ~59 KB of base64, and a step fixed
here but not regenerated there ships a Play that does something else.

```bash
python3 tools/build_play.py            # write play/main.ts
python3 tools/build_play.py --check    # fail if a step changed since it was generated
```

The `--check` form runs in the test suite, so a stale Play is a test failure rather than a
published surprise. `play/deps.toml` declares `python3` and nothing else.

The steps travel as **literal Python in a YAML block scalar**, not base64 — the same way
`modiqo/dns-propagation-check` embeds its own. It costs about the same bytes and buys the thing
base64 destroys: someone inspecting the Play before running it can read exactly what it will do.
`--base64` keeps the opaque form available as a fallback; both modes are tested.

The generator verifies itself. It strips the comment prefix, parses the frontmatter with PyYAML,
and asserts every embedded script round-trips to the exact bytes in `steps/`. A Play that fails
that is never written.

rote's own syntax, confirmed against that reference Play: a parameter is a bare `$root`, a value
edge is `@step{$.stdout.text | fromjson | .packed}`, and the body reads step outputs through the
presentation SDK (`loadPresentationContext`, `ctx.step(stepName(...))`, `out.human()`).

## Optional GITHUB_TOKEN

The GitHub REST API allows 60 unauthenticated requests per hour and a 47-dependency project
exhausts that. `GITHUB_TOKEN` raises it to 5000/hr. It is deliberately **optional**: the Play runs
with no credentials at all and simply reports more `REVIEW` rows without one, which keeps
`rote play inspect` showing *Authentication: none* and setup at zero for anyone adopting it.

`GITHUB_API_BASE` overrides the API root (default `https://api.github.com`) for GitHub Enterprise
installs and for the hermetic tests described above.

## Bugs found while testing

Kept because each one would have shipped silently:

- **crates.io answers 403 without a `User-Agent` header** — would have broken the whole Rust path.
- **PyPI `project_urls` keys are author-supplied and vary in case** — numpy publishes `source`,
  others `Source Code`. Exact-case lookup dropped the repo for numpy and packages like it.
- **Repo normalisation took the last two path segments**, so the tracker URL
  `github.com/numpy/numpy/issues` resolved to the non-existent repo `numpy/issues`.
- **A malformed manifest reported "no manifest found"**, discarding the parse error.
- **`^\s*` under `re.M` matched across newlines**, so Python import line numbers pointed at blank
  lines. Call-site accuracy is this Play's core promise; wrong line numbers destroy it.
- **A commented-out `require()` counted as a live call site**, inflating the very count this Play
  exists to shrink.
- **`re.split` used positional `maxsplit`**, deprecated in Python 3.13+ and liable to emit stderr
  noise inside a step.

## Status

The analysis payload is complete and tested, and the Play is generated end to end from it. The
five-stage chain has been run against a live PyPI and a stub GitHub API, and every failure mode —
empty upstream, malformed upstream, bad root, rate limit, a stage skipped entirely — is covered.

Remaining before publishing: run `rote play lint` and `rote play release`, and get into the
`hackathon` org. See
[`docs/HANDOFF.md`](docs/HANDOFF.md) for the ordered list and [`docs/PLAN.md`](docs/PLAN.md) for
the reasoning.
