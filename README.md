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
| `steps/compute_verdict.py` | Join everything from stdin JSONL into the ranked verdict |

### Step contract

| Situation | Behaviour |
|---|---|
| Expected absence (unknown package, flaky registry, no changelog) | `{"ok": true, "warning": ...}` on stdout, **exit 0** — a labeled degraded row |
| Hard fault (bad invocation, unreadable root) | message on **stderr**, **exit 2** — dependents BLOCKED, `--resume` offered |

stdout is data, exit status is the failure signal. Collections cross step boundaries as a
delimited scalar (`chr(31)` fields, `chr(30)` records) because value-edge jq must resolve to a
scalar. Standard library only, so `deps.toml` declares `python3` and nothing else — no adapter,
no credentials, no declared writes, so a stranger runs it in one command.

## Try it

```bash
./smoke_test.sh /path/to/some/project
```

`smoke_test.sh` is **local verification only, not the exploration path.** Running one script that
does everything would make rote record a single opaque step with no edges — nothing to
parallelize, checkpoint, resume, or blame per source. During the recorded exploration each
reading gets its own `rote proc run` capture, so independent readings become parallel root steps.

## Tests

```bash
python3 -m pytest tests/ -q                    # hermetic
ROTE_NET_TESTS=1 python3 -m pytest tests/ -q   # plus live npm / PyPI / crates.io reads
```

63 tests, all passing. Coverage includes the honesty invariant above, exact call-site line
numbers, comment filtering, vendor-directory exclusion, and the negative space — unknown package,
unsupported ecosystem, empty directory, malformed manifest, empty stdin, bad invocation.

## Optional GITHUB_TOKEN

The GitHub REST API allows 60 unauthenticated requests per hour and a 47-dependency project
exhausts that. `GITHUB_TOKEN` raises it to 5000/hr. It is deliberately **optional**: the Play runs
with no credentials at all and simply reports more `REVIEW` rows without one, which keeps
`rote play inspect` showing *Authentication: none* and setup at zero for anyone adopting it.

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

The analysis payload is complete and tested. `fetch_changelog.py`'s *success* path is the one
unverified piece — the GitHub API was unreachable from the machine it was developed on, so its
parsing, version-range filtering and every degrade path are tested but the happy path needs one
run where GitHub is reachable.

Remaining: install rote (see [`docs/SETUP.md`](docs/SETUP.md)), run the recorded exploration, and
publish. See [`docs/PLAN.md`](docs/PLAN.md).
