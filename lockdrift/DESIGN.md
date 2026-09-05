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

## Status

Built and tested 2026-09-05. 49 tests. Not yet linted, run through rote, or
published — those need the rote CLI.

Two bugs the fixture caught before anything shipped, both in the range reader:

- `parts()` was handed the spec with its operator still attached, so every
  caret and tilde range came back "not evaluated". That silently downgraded a
  genuine out-of-range pin (`^4.17.21` against a locked `4.16.0`) from DRIFT to
  UNCHECKED — the scanner reporting less than it knew.
- A locked package absent from an install tree that *was* read is drift for a
  production dependency (installing adds it) but not for a dev one, where the
  tree may simply be a production install. Calling both drift would have
  invented evidence; calling both unknown would have hidden it.

## Next

    python3 lockdrift/tools/build_play.py
    cp -r lockdrift/play/main.ts lockdrift/play/deps.toml lockdrift/play/resources \
          ~/.rote/flows/lockfile-drift/
    rote play lint lockfile-drift
    rote play run ~/.rote/flows/lockfile-drift/main.ts root=<a real project>
    python3 lockdrift/tools/make_fixtures.py <the run's input.json>
    python3 lockdrift/tools/build_play.py     # declares presentation_fixtures
    rote play lint lockfile-drift && rote play release lockfile-drift
    cd /tmp && rote registry play push ~/.rote/flows/lockfile-drift/main.ts adityagaur
