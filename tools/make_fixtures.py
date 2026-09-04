#!/usr/bin/env python3
"""Build presentation fixtures from a real run's durable input.

    python3 tools/make_fixtures.py <path to .rote/presentation/<run-id>/input.json>

`rote play lint` reports PRESENTATION_FIXTURE_REQUIRED until every data-bearing
step has representative evidence. The evidence has to come from an actual run --
lint will not fabricate a process body -- so this reads one, takes only the
stdout and stderr observations, and writes the manifests `rote grammar steps`
specifies:

    play/resources/presentation-fixtures/<step>/fixture.yaml
    play/resources/presentation-fixtures/<step>/stdout.json
    play/resources/presentation-fixtures/<step>/stderr.txt

Only the streams are packaged. The recorded body also carries cwd, invocation,
artifact paths and environment, and none of that belongs in a published Play.

Pick a run where every step completed: a process fixture represents a completed
observation, so exit must be code 0.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(ROOT, "play", "resources", "presentation-fixtures")

# Kept in step order; timeouts mirror build_play.GRAPH so the manifests agree
# with what the frontmatter declares.
STEPS = [
    ("find_dependencies", 30_000),
    ("resolve_versions", 180_000),
    ("locate_callsites", 90_000),
    ("read_changelogs", 240_000),
    ("rank_verdict", 15_000),
]

MAX_RESOURCE = 1_048_576          # 1 MiB, per rote grammar steps


def die(msg):
    print(f"make_fixtures: {msg}", file=sys.stderr)
    raise SystemExit(2)


def dig(doc, *path):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def stream_text(body, name):
    """stdout/stderr as text, however the recorded body spells it."""
    node = body.get(name)
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        for key in ("text", "content", "value"):
            if isinstance(node.get(key), str):
                return node[key]
    return ""


def main():
    if len(sys.argv) < 2:
        die("usage: make_fixtures.py <path to input.json>\n"
            "  find ~/.rote/workspaces -type f -name input.json -path '*presentation*'")
    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except OSError as exc:
        die(f"cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")

    steps = doc.get("steps")
    if not isinstance(steps, dict):
        die(f"no top-level `steps` map in {path}; keys are {sorted(doc)[:12]}")

    written = []
    for step, timeout_ms in STEPS:
        outcome = dig(steps, step, "outcome")
        if outcome is None:
            die(f"{step}: no outcome recorded. Present: {sorted(steps)}")
        status = outcome.get("status")
        if status not in ("completed", "restored"):
            die(f"{step}: status is {status!r}; a fixture represents a completed "
                f"observation. Re-run the play against a real project and use that run.")

        body = dig(outcome, "output", "body")
        if not isinstance(body, dict):
            die(f"{step}: no outcome.output.body object")

        stdout = stream_text(body, "stdout")
        stderr = stream_text(body, "stderr")
        if not stdout.strip():
            die(f"{step}: recorded stdout is empty; nothing representative to package")
        for label, text in (("stdout", stdout), ("stderr", stderr)):
            if len(text.encode("utf-8")) > MAX_RESOURCE:
                die(f"{step}: {label} is over the 1 MiB resource limit")

        duration = dig(body, "status", "duration_ms") or outcome.get("duration_ms") or 0

        target = os.path.join(FIXTURES, step)
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "stdout.json"), "w", encoding="utf-8") as handle:
            handle.write(stdout if stdout.endswith("\n") else stdout + "\n")
        # An empty stream is explicit only when its resource file is empty.
        with open(os.path.join(target, "stderr.txt"), "w", encoding="utf-8") as handle:
            handle.write(stderr)
        rel = f"resources/presentation-fixtures/{step}"
        with open(os.path.join(target, "fixture.yaml"), "w", encoding="utf-8") as handle:
            handle.write(
                "schema_version: 1\n"
                "kind: process.exec\n"
                "status:\n"
                "  exit: { kind: code, code: 0 }\n"
                f"  duration_ms: {int(duration)}\n"
                f"  timeout_ms: {timeout_ms}\n"
                f"stdout: {rel}/stdout.json\n"
                f"stderr: {rel}/stderr.txt\n")
        written.append((step, len(stdout), len(stderr)))

    print(f"wrote {len(written)} fixtures under "
          f"{os.path.relpath(FIXTURES, ROOT)}/")
    for step, out_len, err_len in written:
        print(f"  {step:<20} stdout {out_len:>6} B   stderr {err_len:>4} B")
    print("\nnow: python3 tools/build_play.py   (declares presentation_fixtures:)")


if __name__ == "__main__":
    main()
