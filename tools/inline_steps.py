#!/usr/bin/env python3
"""Emit self-contained `python3 -c` invocations for each step script.

A recorded capture bakes in the absolute path it was run from:

    python3 /home/adity/rote-playoffs-hack-26/steps/parse_manifest.py <root>

That path exists on one machine. A published Play has to run for a stranger
who pulled it fresh, so the exported main.ts must carry the scripts rather
than point at them.

Base64 is what makes this safe: the encoded body is alphanumeric plus +/=,
so it survives any shell, argv array or TypeScript string literal without
quoting or escaping. Arguments still land in sys.argv[1:] exactly as they do
when the file is run directly, so no step script needs to change.

    python3 tools/inline_steps.py            # human-readable
    python3 tools/inline_steps.py --json     # {step: [argv prefix]}
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = os.path.join(os.path.dirname(HERE), "steps")
BOOTSTRAP = "import base64;exec(base64.b64decode('{}').decode())"


def argv_prefix(path):
    """The ["python3", "-c", <program>] prefix that runs `path` inline."""
    with open(path, "rb") as handle:
        blob = base64.b64encode(handle.read()).decode("ascii")
    return ["python3", "-c", BOOTSTRAP.format(blob)]


def steps():
    for name in sorted(os.listdir(STEPS)):
        if name.endswith(".py"):
            yield name[:-3], argv_prefix(os.path.join(STEPS, name))


def main():
    table = dict(steps())
    if "--json" in sys.argv[1:]:
        sys.stdout.write(json.dumps(table, indent=2) + "\n")
        return
    for name, prefix in table.items():
        program = prefix[2]
        sys.stdout.write(f"{name}  ({len(program)} chars)\n")
        sys.stdout.write(f"  argv: [\"python3\", \"-c\", \"{program}\", ...args]\n\n")


if __name__ == "__main__":
    main()
