"""Tests for the lockfile-drift steps.

The readers are exercised against real files on disk; the join is exercised
against real reader output, so nothing here asserts against a hand-built
payload the steps never actually produce.
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = os.path.join(os.path.dirname(HERE), "steps")

FS = chr(31)
RS = chr(30)


def run(script, *args):
    return subprocess.run([sys.executable, os.path.join(STEPS, script), *args],
                          capture_output=True, text=True)


def read(script, root):
    proc = run(script, str(root))
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def compare(declared, locked, installed):
    proc = run("compare_pins.py", "--from-steps", declared, locked, installed)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def chain(root):
    return compare(read("read_declared.py", root),
                   read("read_locked.py", root),
                   read("read_installed.py", root))


def tiers(out):
    return {row.split(FS)[2]: row.split(FS)[0]
            for row in out["packed"].split(RS) if row}


def npm_project(tmp_path, deps, dev=None, lock=None, installed=None,
                lockfile_version=3):
    (tmp_path / "package.json").write_text(json.dumps(
        {"name": "demo", "dependencies": deps, "devDependencies": dev or {}}))
    if lock is not None:
        if lockfile_version == 3:
            doc = {"name": "demo", "lockfileVersion": 3, "packages": {
                "": {"name": "demo"},
                **{f"node_modules/{n}": v if isinstance(v, dict) else {"version": v}
                   for n, v in lock.items()}}}
        else:
            doc = {"name": "demo", "lockfileVersion": 1, "dependencies": {
                n: v if isinstance(v, dict) else {"version": v}
                for n, v in lock.items()}}
        (tmp_path / "package-lock.json").write_text(json.dumps(doc))
    if installed is not None:
        for name, version in installed.items():
            pkg = tmp_path / "node_modules" / name
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text(
                json.dumps({"name": name, "version": version}))
    return tmp_path


# --------------------------------------------------------------------------
# The four tiers
# --------------------------------------------------------------------------

def test_lock_and_install_disagreeing_is_drift(tmp_path):
    npm_project(tmp_path, {"express": "^4.18.0"},
                lock={"express": "4.18.2"}, installed={"express": "4.17.1"})
    out = chain(tmp_path)
    assert tiers(out) == {"express": "DRIFT"}
    assert "4.18.2" in out["report"] and "4.17.1" in out["report"]


def test_a_lock_outside_the_declared_range_is_drift(tmp_path):
    npm_project(tmp_path, {"lodash": "^4.17.21"},
                lock={"lodash": "4.16.0"}, installed={})
    out = chain(tmp_path)
    assert tiers(out) == {"lodash": "DRIFT"}
    assert "outside the declared" in out["report"]


def test_declared_with_no_lock_entry_is_unlocked(tmp_path):
    npm_project(tmp_path, {"chalk": "^5.0.0"}, lock={"other": "1.0.0"}, installed={})
    out = chain(tmp_path)
    assert tiers(out)["chalk"] == "UNLOCKED"


def test_all_three_agreeing_is_synced(tmp_path):
    npm_project(tmp_path, {"axios": "^1.6.0"},
                lock={"axios": "1.6.8"}, installed={"axios": "1.6.8"})
    out = chain(tmp_path)
    assert tiers(out) == {"axios": "SYNCED"}
    assert out["synced"] == 1 and out["drift"] == 0


# --------------------------------------------------------------------------
# The invariant: a source that was not read is never reported as agreement
# --------------------------------------------------------------------------

def test_with_no_install_tree_nothing_can_be_synced(tmp_path):
    npm_project(tmp_path, {"axios": "^1.6.0", "express": "^4.18.0"},
                lock={"axios": "1.6.8", "express": "4.18.2"})
    out = chain(tmp_path)
    assert out["installed_observed"] is False
    assert out["synced"] == 0, "claimed agreement with a tree nobody read"
    assert set(tiers(out).values()) == {"UNCHECKED"}
    assert "NOT observed" in out["report"]


def test_a_missing_install_tree_does_not_hide_findings_from_other_sources(tmp_path):
    """Degrading one source must not suppress what the others prove."""
    npm_project(tmp_path, {"lodash": "^4.17.21"}, lock={"lodash": "4.16.0"})
    out = chain(tmp_path)
    assert out["installed_observed"] is False
    assert tiers(out) == {"lodash": "DRIFT"}


def test_with_no_lockfile_every_dependency_is_unchecked_not_synced(tmp_path):
    npm_project(tmp_path, {"axios": "^1.6.0"}, installed={"axios": "1.6.8"})
    out = chain(tmp_path)
    assert out["synced"] == 0
    assert tiers(out) == {"axios": "UNCHECKED"}
    assert "no lockfile" in out["report"]


def test_an_unparseable_lockfile_is_reported_not_swallowed(tmp_path):
    npm_project(tmp_path, {"axios": "^1.6.0"}, installed={"axios": "1.6.8"})
    (tmp_path / "package-lock.json").write_text("{ not json")
    locked = json.loads(read("read_locked.py", tmp_path))
    assert locked["unreadable"] == 1
    assert "package-lock.json" in locked["warning"]
    out = chain(tmp_path)
    assert out["synced"] == 0


# --------------------------------------------------------------------------
# Range evaluation — narrow on purpose
# --------------------------------------------------------------------------

@pytest.mark.parametrize("spec,locked,expected", [
    ("^1.6.0", "1.6.8", "SYNCED"),          # caret, in range
    ("^1.6.0", "2.0.0", "DRIFT"),           # caret, major moved
    ("^0.2.3", "0.2.9", "SYNCED"),          # caret 0.x pins the minor
    ("^0.2.3", "0.3.0", "DRIFT"),
    ("~1.2.3", "1.2.9", "SYNCED"),          # tilde pins the minor
    ("~1.2.3", "1.3.0", "DRIFT"),
    (">=1.2.0", "9.9.9", "SYNCED"),
    (">=1.2.0", "1.1.0", "DRIFT"),
    ("1.6.8", "1.6.8", "SYNCED"),           # exact
    ("1.6.8", "1.6.9", "DRIFT"),
    ("*", "1.6.8", "SYNCED"),
])
def test_range_forms_that_are_evaluated(tmp_path, spec, locked, expected):
    npm_project(tmp_path, {"pkg": spec}, lock={"pkg": locked},
                installed={"pkg": locked})
    assert tiers(chain(tmp_path)) == {"pkg": expected}


@pytest.mark.parametrize("spec", [
    "^17 || ^18",                 # union
    "1.2.0 - 2.0.0",              # hyphen range
    "git+https://x/y.git",        # git reference
    "file:../local",              # path reference
    "workspace:*",                # workspace protocol
])
def test_range_forms_that_are_refused_rather_than_guessed(tmp_path, spec):
    """A false DRIFT costs more trust than a missed one."""
    npm_project(tmp_path, {"pkg": spec}, lock={"pkg": "18.2.0"},
                installed={"pkg": "18.2.0"})
    out = chain(tmp_path)
    assert tiers(out) == {"pkg": "UNCHECKED"}
    assert "not evaluated" in out["report"]


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------

def test_lockfile_version_1_and_3_are_both_read(tmp_path):
    for version in (1, 3):
        root = tmp_path / f"v{version}"
        root.mkdir()
        npm_project(root, {"axios": "^1.6.0"}, lock={"axios": "1.6.8"},
                    installed={"axios": "1.6.8"}, lockfile_version=version)
        assert tiers(chain(root)) == {"axios": "SYNCED"}, f"lockfileVersion {version}"


def test_nested_lock_entries_are_not_read_as_top_level(tmp_path):
    """Only hoisted installs; a transitive copy is a different question."""
    npm_project(tmp_path, {"axios": "^1.6.0"}, lock={"axios": "1.6.8"})
    doc = json.loads((tmp_path / "package-lock.json").read_text())
    doc["packages"]["node_modules/axios/node_modules/follow-redirects"] = {"version": "1.0.0"}
    (tmp_path / "package-lock.json").write_text(json.dumps(doc))
    locked = json.loads(read("read_locked.py", tmp_path))
    names = {row.split(FS)[1] for row in locked["packed"].split(RS) if row}
    assert names == {"axios"}


def test_scoped_packages_are_read(tmp_path):
    npm_project(tmp_path, {"@scope/pkg": "^1.0.0"}, lock={"@scope/pkg": "1.0.2"})
    pkg = tmp_path / "node_modules" / "@scope" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({"name": "@scope/pkg", "version": "1.0.2"}))
    assert tiers(chain(tmp_path)) == {"@scope/pkg": "SYNCED"}


def test_a_dev_dependency_absent_from_the_tree_is_unknown_not_drift(tmp_path):
    """It may simply be a production install, and guessing would invent evidence."""
    npm_project(tmp_path, {"axios": "^1.6.0"}, dev={"jest": "^29.0.0"},
                lock={"axios": "1.6.8", "jest": {"version": "29.7.0", "dev": True}},
                installed={"axios": "1.6.8"})
    out = chain(tmp_path)
    assert tiers(out)["jest"] == "UNCHECKED"
    assert "production install" in out["report"]


def test_python_sources_are_read(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["numpy>=1.26", "requests==2.31.0"]\n')
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "numpy"\nversion = "2.5.2"\n\n'
        '[[package]]\nname = "requests"\nversion = "2.31.0"\n')
    site = tmp_path / ".venv" / "lib" / "python3.11" / "site-packages"
    (site / "numpy-2.5.2.dist-info").mkdir(parents=True)
    (site / "requests-2.31.0.dist-info").mkdir(parents=True)
    out = chain(tmp_path)
    assert tiers(out) == {"numpy": "SYNCED", "requests": "SYNCED"}


def test_an_unparseable_manifest_is_a_visible_unknown(tmp_path):
    (tmp_path / "package.json").write_text("{ not json at all")
    declared = json.loads(read("read_declared.py", tmp_path))
    assert declared["ok"] is True
    assert declared["unreadable"] == 1
    assert "package.json" in declared["warning"]


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------

def test_an_empty_directory_degrades_rather_than_failing(tmp_path):
    out = chain(tmp_path)
    assert out["ok"] is True
    assert out["total"] == 0
    assert "nothing declared" in out["report"]


@pytest.mark.parametrize("script", ["read_declared.py", "read_locked.py",
                                    "read_installed.py"])
def test_a_missing_root_is_a_hard_fault(script):
    proc = run(script, "/nope/does/not/exist")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr
    assert proc.stdout == ""


def test_a_malformed_upstream_payload_fails_closed(tmp_path):
    good = read("read_declared.py", tmp_path)
    proc = run("compare_pins.py", "--from-steps", good, '{"source": "locked"',
               '{"source": "installed"}')
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_a_truncated_upstream_payload_is_named(tmp_path):
    npm_project(tmp_path, {f"package-with-a-realistic-name-{i}": "^1.0.0"
                           for i in range(900)},
                lock={f"package-with-a-realistic-name-{i}": "1.0.0"
                      for i in range(900)})
    locked = read("read_locked.py", tmp_path)
    assert len(locked) > 65536, "fixture must exceed the cap it is testing"
    proc = run("compare_pins.py", "--from-steps", read("read_declared.py", tmp_path),
               locked[:65536], read("read_installed.py", tmp_path))
    assert proc.returncode == 2
    assert "ends mid-value" in proc.stderr
    assert proc.stdout == ""


def test_the_readers_must_arrive_in_the_declared_order(tmp_path):
    """A mis-wired edge is a broken invocation, not a silent wrong answer."""
    declared = read("read_declared.py", tmp_path)
    locked = read("read_locked.py", tmp_path)
    installed = read("read_installed.py", tmp_path)
    proc = run("compare_pins.py", "--from-steps", locked, declared, installed)
    assert proc.returncode == 2
    assert "expected the declared reading" in proc.stderr


# --------------------------------------------------------------------------
# The generated Play — the same guards that caught real problems in the first
# --------------------------------------------------------------------------

TOOLS = os.path.join(os.path.dirname(HERE), "tools")
PLAY = os.path.join(os.path.dirname(HERE), "play")


def _play():
    with open(os.path.join(PLAY, "main.ts")) as handle:
        return handle.read()


def _frontmatter(play):
    yaml = pytest.importorskip("yaml")
    inner = play.split("/**\n", 1)[1].split("\n */\n", 1)[0]
    stripped = "\n".join(
        line[3:] if line.startswith(" * ") else line[2:] if line.startswith(" *") else line
        for line in inner.split("\n"))
    return yaml.safe_load(stripped.split("---\n", 1)[1].rsplit("---", 1)[0])


def test_the_published_play_is_not_stale():
    proc = subprocess.run(
        [sys.executable, os.path.join(TOOLS, "build_play.py"), "--check"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_no_step_smuggles_code_into_argv():
    """rote caps an inline argv element at 256 chars and rejects line breaks."""
    doc = _frontmatter(_play())
    for step, spec in doc["steps"].items():
        for i, arg in enumerate(spec["argv"]):
            assert "\n" not in arg, f"{step}: argv[{i}] contains a line break"
            assert len(arg) <= 256, f"{step}: argv[{i}] is {len(arg)} chars"


def test_the_three_readers_are_parallel_roots():
    """They share no state and depend only on root; the DAG must say so."""
    doc = _frontmatter(_play())
    for reader in ("read_declared", "read_locked", "read_installed"):
        assert "depends_on" not in doc["steps"][reader], f"{reader} is not a root"
        assert "$root" in doc["steps"][reader]["argv"]
    join = doc["steps"]["compare_pins"]
    assert set(join["depends_on"]) == {"read_declared", "read_locked", "read_installed"}


def test_the_join_reads_each_reader_whole():
    """It needs `source` to verify wiring and `observed` to honour the invariant,
    so a projection onto one field would silently break both."""
    doc = _frontmatter(_play())
    argv = doc["steps"]["compare_pins"]["argv"]
    for reader in ("read_declared", "read_locked", "read_installed"):
        assert f"@{reader}{{$.stdout.text}}" in argv, reader


def test_each_step_names_its_script_by_resource_token():
    doc = _frontmatter(_play())
    for step in ("read_declared", "read_locked", "read_installed", "compare_pins"):
        assert doc["steps"][step]["argv"][1] == "@resource{%s.py}" % step


def test_the_play_carries_no_local_path():
    play = _play()
    for local in ("/home/", "steps/", os.path.dirname(HERE)):
        assert local not in play, f"main.ts references {local}"


@pytest.mark.parametrize("script", ["read_declared", "read_locked",
                                    "read_installed", "compare_pins"])
def test_published_resource_matches_the_tested_script(script):
    with open(os.path.join(STEPS, f"{script}.py")) as handle:
        tested = handle.read()
    with open(os.path.join(PLAY, "resources", f"{script}.py")) as handle:
        assert handle.read() == tested, f"play/resources/{script}.py is stale"


def test_every_required_tool_has_an_install_candidate():
    tomllib = pytest.importorskip("tomllib")
    with open(os.path.join(PLAY, "deps.toml"), "rb") as handle:
        manifest = tomllib.load(handle)
    assert set(manifest) <= {"schema_version", "tools", "files", "readiness"}
    for tool in manifest["tools"]:
        if tool.get("required"):
            managers = {c["manager"] for c in tool.get("install") or []}
            assert {"brew", "apt"} <= managers, f"{tool['id']}: {sorted(managers)}"


def test_every_shipped_resource_parses_at_the_declared_floor():
    """The floor claim in deps.toml has to be true, not aspirational."""
    import ast
    for name in sorted(os.listdir(os.path.join(PLAY, "resources"))):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(PLAY, "resources", name)) as handle:
            ast.parse(handle.read(), feature_version=(3, 8))


# --------------------------------------------------------------------------
# The pyproject reader must not invent dependencies
#
# Found on the first real run: an ordinary pyproject reported `EcoSlice
# contributors`, `src` and `tests` as declared dependencies, because the reader
# matched any `key = [...]` anywhere in the file. A reader that invents rows is
# the same failure as one that hides them, pointed the other way.
# --------------------------------------------------------------------------

REALISTIC_PYPROJECT = '''[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "ecoslice"
authors = [{name = "EcoSlice contributors"}]
classifiers = ["Programming Language :: Python :: 3", "License :: OSI Approved"]
keywords = ["fem", "meshing"]
dependencies = ["numpy>=1.26", "scipy>=1.11", "pyamg>=5.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools]
packages = ["src", "tests"]
'''


def test_only_dependency_tables_are_read(tmp_path):
    (tmp_path / "pyproject.toml").write_text(REALISTIC_PYPROJECT)
    out = json.loads(read("read_declared.py", tmp_path))
    found = {row.split(FS)[1] for row in out["packed"].split(RS) if row}
    assert found == {"numpy", "scipy", "pyamg", "pytest"}
    for invented in ("EcoSlice", "src", "tests", "wheel", "Programming", "fem"):
        assert invented not in found, f"{invented} is not a dependency"


def test_build_requirements_are_not_your_dependencies(tmp_path):
    """They install into the build environment, not yours."""
    (tmp_path / "pyproject.toml").write_text(REALISTIC_PYPROJECT)
    out = json.loads(read("read_declared.py", tmp_path))
    found = {row.split(FS)[1] for row in out["packed"].split(RS) if row}
    assert "setuptools" not in found


def test_optional_dependency_groups_are_labelled(tmp_path):
    (tmp_path / "pyproject.toml").write_text(REALISTIC_PYPROJECT)
    out = json.loads(read("read_declared.py", tmp_path))
    sections = {row.split(FS)[1]: row.split(FS)[4]
                for row in out["packed"].split(RS) if row}
    assert sections["pytest"] == "optional:dev"
    assert sections["numpy"] == "project"


def test_poetry_dependencies_are_read(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "demo"\n\n[tool.poetry.dependencies]\n'
        'python = "^3.9"\nrequests = "^2.31.0"\n'
        'numpy = { version = "1.26.4", optional = true }\n')
    out = json.loads(read("read_declared.py", tmp_path))
    found = {row.split(FS)[1]: row.split(FS)[2]
             for row in out["packed"].split(RS) if row}
    assert found == {"requests": "^2.31.0", "numpy": "1.26.4"}, "python is not a dependency"


def test_a_multiline_dependency_array_is_read(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = [\n'
        '    "numpy>=1.26",   # trailing comments must not break it\n'
        '    "scipy==1.11",\n]\n\n[tool.setuptools]\npackages = ["src"]\n')
    out = json.loads(read("read_declared.py", tmp_path))
    found = {row.split(FS)[1] for row in out["packed"].split(RS) if row}
    assert found == {"numpy", "scipy"}
