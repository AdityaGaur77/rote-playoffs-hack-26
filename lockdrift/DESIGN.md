# lockfile-drift

**Which dependencies would change if you installed right now?**

Three sources disagree more often than anyone checks:

| Source | What it says |
|---|---|
| manifest | `"express": "^4.18.0"` — a *range* |
| lockfile | `express 4.18.2` — a *pin* |
| installed tree | `node_modules/express` is actually `4.17.1` |

`npm outdated` compares you to the registry. This compares you to **yourself**.

## Tiers

| Tier | Meaning |
|---|---|
| `DRIFT` | The three sources disagree in a way your next install will act on |
| `UNLOCKED` | Declared, but no lock entry — the version is whatever the day decides |
| `UNCHECKED` | A source could not be read for this dependency; nobody verified it |
| `SYNCED` | The sources that exist agree |

## The honesty invariant

Same shape as upgrade-impact-triage, and the reason to trust either:

- **A source that could not be read is never reported as agreement.** No
  `node_modules`? Then the installed state was *not observed* — say so, do not
  say it matches.
- An unparseable lockfile produces `UNCHECKED` rows, never `SYNCED` ones.
- `SYNCED` always names *which* sources were compared. Two-of-three agreeing is
  not the same claim as three-of-three, and the output must not blur them.

Running it with nothing installed yields more `UNCHECKED`, never fewer warnings.

## The DAG

The three readers touch no shared state and depend on nothing but `root`, so
they are parallel root steps and the join fans in:

    read_declared   ─┐
    read_locked     ─┼─→ compare_pins
    read_installed  ─┘

Two layers, three-way parallelism. (upgrade-impact-triage is linear because its
stages genuinely feed each other; this one is not, and should not pretend to be.)

## Scope, stated up front

Reads npm (`package.json` / `package-lock.json` / `node_modules`) and Python
(`pyproject.toml`, `requirements*.txt` / `uv.lock`, `poetry.lock` /
`site-packages`). It never installs, never resolves against a registry, and
never runs a package manager — so it cannot tell you what the *newest* version
is, only whether the three things on your disk agree.

## Status — published

`adityagaur/lockfile-drift@0.1.1`, public, 13,244 bytes. `rote play lint`
passes with **zero findings**; presentation fixtures cut from
`run_20260905_211752.734_4`.

The DAG runs as designed — rote's own labelling:

```
  [layer 1 — 3 parallel]
    read_declared  @5  (31ms)
    read_locked    @6  (30ms)
    read_installed @7  (31ms)
  [layer 2]
    compare_pins   @8  (31ms)
  Summary: 4/4 completed   Duration: 175ms
```

And the invariant held on a real tree with no lockfile and no venv: two stages
degraded with named reasons, four UNCHECKED, **zero SYNCED**.

## Two bugs, both caught by running it rather than by testing it

- The range reader was handed specs with the operator still attached, so every
  caret and tilde came back "not evaluated" — which silently downgraded a
  genuine out-of-range pin from DRIFT to UNCHECKED. Caught by the fixture,
  before release.
- Published 0.1.0 reported `EcoSlice contributors`, `src` and `tests` as
  declared dependencies: the reader matched any `key = [...]` anywhere in the
  file. Ten rows where four were real, each with a confident verdict attached.
  Caught by the first run against a real project. Fixed in 0.1.1 — the reader
  is section-aware and takes only `[project] dependencies`,
  `[project.optional-dependencies]` and `[tool.poetry.dependencies]`.

A reader that invents rows is the same failure as one that hides them, pointed
the other way. It is arguably worse: a missing row is silence, an invented row
is a claim.
