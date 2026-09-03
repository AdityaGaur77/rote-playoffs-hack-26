"""Tests for the upgrade-impact-triage step scripts.

Pure-function tests import the modules directly. Behavioural tests shell out,
because the thing under test is the step contract itself: what lands on stdout,
what lands on stderr, and the exit status.

Network tests are opt-in — run with ROTE_NET_TESTS=1 to exercise the live npm,
PyPI and crates.io endpoints. Off by default so the suite stays hermetic.
"""
import base64
import http.server
import itertools
import json
import os
import subprocess
import sys
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = os.path.join(os.path.dirname(HERE), "steps")
sys.path.insert(0, STEPS)

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import compute_verdict          # noqa: E402
import fetch_changelog          # noqa: E402
import fetch_registry           # noqa: E402
import inline_steps             # noqa: E402
import parse_manifest           # noqa: E402

FS = chr(31)
RS = chr(30)

needs_net = pytest.mark.skipif(
    os.environ.get("ROTE_NET_TESTS") != "1",
    reason="set ROTE_NET_TESTS=1 to run tests that hit live registries",
)


def run(script, *args, stdin=None, env=None):
    proc = subprocess.run(
        [sys.executable, os.path.join(STEPS, script), *args],
        capture_output=True, text=True, input=stdin,
        env={**os.environ, **env} if env else None,
    )
    return proc


def unpack(packed):
    return [row.split(FS) for row in packed.split(RS)] if packed else []


# --------------------------------------------------------------------------
# parse_manifest
# --------------------------------------------------------------------------

def test_parses_package_json_and_skips_unresolvable_specs(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {
            "left-pad": "^1.3.0",
            "express": "~4.17.1",
            "local": "file:../local",       # no registry can resolve these
            "forked": "git+https://github.com/x/y.git",
            "ws": "workspace:*",
        },
        "devDependencies": {"jest": "^29.0.0"},
    }))
    out = json.loads(run("parse_manifest.py", str(tmp_path)).stdout)
    names = {r[1] for r in unpack(out["packed"])}
    assert names == {"left-pad", "express", "jest"}
    assert out["ecosystems"] == "npm"


def test_parses_cargo_and_skips_path_dependencies(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname="d"\n'
        '[dependencies]\nserde="1.0.150"\nrand={version="0.8.5"}\n'
        'mylocal={path="../mylocal"}\n'
    )
    out = json.loads(run("parse_manifest.py", str(tmp_path)).stdout)
    assert {r[1] for r in unpack(out["packed"])} == {"serde", "rand"}


def test_parses_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "requests>=2.20.0\n# a comment\n\n-e .\nnumpy==1.26.0  # inline\n")
    out = json.loads(run("parse_manifest.py", str(tmp_path)).stdout)
    assert {r[1] for r in unpack(out["packed"])} == {"requests", "numpy"}


def test_version_specs_are_normalised():
    assert parse_manifest.clean_version("^1.2.3") == "1.2.3"
    assert parse_manifest.clean_version("~4.17.1") == "4.17.1"
    assert parse_manifest.clean_version(">=2.0") == "2.0"
    assert parse_manifest.clean_version("*") == ""


def test_missing_root_is_a_hard_fault():
    proc = run("parse_manifest.py", "/definitely/not/here")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr


def test_empty_directory_degrades_rather_than_failing(tmp_path):
    proc = run("parse_manifest.py", str(tmp_path))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["ok"] is True and out["count"] == 0
    assert "no supported manifest" in out["warning"]


def test_unparseable_manifest_names_the_real_cause(tmp_path):
    """A degraded source must be a visible unknown, never a silent one."""
    (tmp_path / "package.json").write_text("{ not json")
    proc = run("parse_manifest.py", str(tmp_path))
    assert proc.returncode == 0
    warning = json.loads(proc.stdout)["warning"]
    assert "failed to parse" in warning and "package.json" in warning


# --------------------------------------------------------------------------
# fetch_registry
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/numpy/numpy/issues", "numpy/numpy"),   # tracker, not a repo
    ("https://github.com/numpy/numpy", "numpy/numpy"),
    ("git+https://github.com/psf/requests.git", "psf/requests"),
    ("git://github.com/expressjs/express.git", "expressjs/express"),
    ("https://github.com/serde-rs/serde/tree/master/serde", "serde-rs/serde"),
    ("https://gitlab.com/foo/bar", ""),
    ("https://numpy.org", ""),
    (None, ""),
])
def test_repo_urls_normalise_to_owner_name(url, expected):
    assert fetch_registry.norm_repo(url) == expected


def test_project_url_keys_are_matched_case_insensitively():
    """PyPI project_urls keys are author-supplied; numpy uses lowercase 'source'."""
    numpy_style = {"homepage": "https://numpy.org",
                   "source": "https://github.com/numpy/numpy",
                   "tracker": "https://github.com/numpy/numpy/issues"}
    assert fetch_registry.repo_from_urls(numpy_style) == "numpy/numpy"

    other_style = {"Source Code": "https://github.com/psf/requests"}
    assert fetch_registry.repo_from_urls(other_style) == "psf/requests"


def test_repo_falls_back_to_any_github_url():
    assert fetch_registry.repo_from_urls(
        {"docs": "https://github.com/a/b/wiki"}) == "a/b"
    assert fetch_registry.repo_from_urls({"docs": "https://example.com"}) == ""


@pytest.mark.parametrize("cur,new,gap", [
    ("4.17.1", "5.2.1", "major"),
    ("2.20.0", "2.34.2", "minor"),
    ("1.0.150", "1.0.229", "patch"),
    ("1.3.0", "1.3.0", "none"),
    ("2.0.0", "1.0.0", "ahead"),
    ("", "1.0.0", "unknown"),
])
def test_version_gap_classification(cur, new, gap):
    assert fetch_registry.gap_between(cur, new) == gap


def test_unsupported_ecosystem_degrades():
    proc = run("fetch_registry.py", "cpan", "Some::Module", "1.0")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["ok"] is True and "unsupported ecosystem" in out["warning"]


def test_bad_invocation_is_a_hard_fault():
    proc = run("fetch_registry.py", "npm")
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


@needs_net
@pytest.mark.parametrize("eco,name", [
    ("npm", "left-pad"), ("pypi", "requests"), ("crates", "serde")])
def test_live_registry_reads(eco, name):
    out = json.loads(run("fetch_registry.py", eco, name, "0.0.1").stdout)
    assert out["latest"], f"no version returned for {eco}/{name}"
    assert out["repo"], f"no source repo resolved for {eco}/{name}"


@needs_net
def test_unknown_package_degrades_not_crashes():
    proc = run("fetch_registry.py", "pypi", "this-package-does-not-exist-zzq", "1.0")
    assert proc.returncode == 0
    assert "not found" in json.loads(proc.stdout)["warning"]


# --------------------------------------------------------------------------
# fetch_changelog
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tag,expected", [
    ("v2.0.0", (2, 0, 0)), ("2.1.3", (2, 1, 3)),
    ("rel-1.2", (1, 2, 0)), ("nightly", None)])
def test_release_tags_yield_versions(tag, expected):
    assert fetch_changelog.tag_version(tag) == expected


@pytest.mark.parametrize("body,label", [
    ("BREAKING CHANGE: dropped Python 3.7", "breaking-change"),
    ("## Breaking\n- the old API is gone", "breaking-heading"),
    ("- Removed the `foo()` helper", "removal"),
    ("We renamed `parse` to `load`", "rename"),
    ("This is backwards-incompatible with 1.x", "incompatible"),
    ("`sniff()` will no longer guess encodings", "no-longer"),
    ("See the migration guide before upgrading", "migration-guide"),
])
def test_breaking_wording_is_detected(body, label):
    hits = {lab for pat, lab in fetch_changelog.BREAKING_PATTERNS if pat.search(body)}
    assert label in hits


@pytest.mark.parametrize("body", [
    "Fixed a typo and improved performance",
    "Added a new optional parameter",
    "Bumped the minimum supported version of a dev dependency",
])
def test_routine_release_notes_are_not_flagged(body):
    hits = {lab for pat, lab in fetch_changelog.BREAKING_PATTERNS if pat.search(body)}
    assert hits == set()


def test_missing_repo_reports_unknown_not_safe():
    """No repo means we could not check, which is not the same as 'no breaking changes'."""
    out = json.loads(run("fetch_changelog.py", "", "1.0", "2.0").stdout)
    assert out["checked"] is False
    assert "cannot read release notes" in out["warning"]


# --- fetch_changelog: the success path, against a stub GitHub API ----------
#
# The live GitHub API is unreachable from some networks (and rate-limits the
# rest), so the path that actually reads release notes is exercised against a
# local stub via GITHUB_API_BASE. Everything below the socket is the real code.

class _StubHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                     # noqa: N802
        status, headers, body = self.server.reply
        if not self.path.startswith("/repos/"):
            status, headers, body = 404, {}, b"{}"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):                         # keep pytest output clean
        pass


class _Stub:
    def __init__(self, server):
        self._server = server
        host, port = server.server_address[:2]
        self.base = f"http://{host}:{port}"

    def reply(self, payload, status=200, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self._server.reply = (status, headers or {}, body)

    @property
    def env(self):
        return {"GITHUB_API_BASE": self.base, "GITHUB_TOKEN": ""}


@pytest.fixture
def github_stub():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.reply = (200, {}, b"[]")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Stub(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _release(tag, body="Fixed a typo.", draft=False):
    return {"tag_name": tag, "body": body, "draft": draft}


def _changelog(stub, current, latest):
    proc = run("fetch_changelog.py", "numpy/numpy", current, latest, env=stub.env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_read_notes_report_breaking_with_samples(github_stub):
    github_stub.reply([
        _release("v1.27.0", "BREAKING CHANGE: dropped the `foo()` helper"),
        _release("v1.26.5", "Fixed a typo."),          # at current, out of range
        _release("v2.0.0", "See the migration guide before upgrading"),
    ])
    out = _changelog(github_stub, "1.26.5", "2.0.0")

    assert out["ok"] is True
    assert out["checked"] is True
    assert out["breaking"] is True
    assert out["releases"] == 2                        # v1.26.5 is excluded
    assert set(out["markers"].split(",")) == {"breaking-change", "migration-guide"}

    samples = unpack(out["packed"])
    assert [row[0] for row in samples] == ["v1.27.0", "v2.0.0"]
    assert all(len(row) == 3 and row[2] for row in samples)


def test_read_notes_on_a_clean_minor_bump_report_not_breaking(github_stub):
    github_stub.reply([_release("v1.27.0"), _release("v1.28.0", "Added an optional flag.")])
    out = _changelog(github_stub, "1.26.0", "1.28.0")

    assert out["checked"] is True
    assert out["breaking"] is False
    assert out["releases"] == 2
    assert out["markers"] == ""
    assert out["packed"] == ""


def test_clean_notes_never_clear_a_major_bump(github_stub):
    """Silence in the notes does not out-vote the major version number."""
    github_stub.reply([_release("v2.0.0", "Performance improvements.")])
    out = _changelog(github_stub, "1.26.0", "2.0.0")

    assert out["checked"] is True
    assert out["breaking"] is True
    assert out["markers"] == "major-version-bump"
    assert "major version changed" in out["note"]


def test_draft_releases_are_ignored(github_stub):
    github_stub.reply([
        _release("v1.27.0", "BREAKING CHANGE: unreleased and unshipped", draft=True),
        _release("v1.28.0", "Added an optional flag."),
    ])
    out = _changelog(github_stub, "1.26.0", "1.28.0")

    assert out["releases"] == 1
    assert out["breaking"] is False


def test_releases_outside_the_range_count_as_unchecked(github_stub):
    github_stub.reply([_release("v0.9.0"), _release("v3.0.0", "BREAKING CHANGE: much later")])
    out = _changelog(github_stub, "1.26.0", "2.0.0")

    assert out["checked"] is False                     # nothing in range was read
    assert out["breaking"] is False
    assert "no releases found between 1.26.0 and 2.0.0" in out["warning"]
    assert out["markers"] == "major-version-bump"      # the bump still speaks


def test_repository_without_releases_is_unknown_not_safe(github_stub):
    github_stub.reply({"message": "Not Found"}, status=404)
    out = _changelog(github_stub, "1.26.0", "2.0.0")

    assert out["ok"] is True
    assert out["checked"] is False
    assert out["breaking"] is False
    assert "no releases published" in out["warning"]


def test_rate_limit_is_reported_and_still_flags_a_major_bump(github_stub):
    github_stub.reply({"message": "rate limited"}, status=403,
                      headers={"X-RateLimit-Remaining": "0"})
    out = _changelog(github_stub, "1.26.0", "2.0.0")

    assert out["ok"] is True                           # an expected absence, not a crash
    assert out["checked"] is False
    assert out["rate_limited"] is True
    assert "rate limit" in out["warning"]
    assert out["markers"] == "major-version-bump"


@pytest.mark.parametrize("tag,expected", [
    ("v2.5.0rc1", True), ("v2.4.0-rc.2", True), ("v1.0.0-beta.1", True),
    ("v1.2.3a1", True), ("v3.0.0-alpha", True), ("v1.0.0.dev1", True),
    ("v2.5.0", False), ("v1.26.4", False), ("2024.1.0", False),
    ("v1.2.3-abc", False),                      # not an alpha, just a word
])
def test_prerelease_tags_are_recognised(tag, expected):
    assert fetch_changelog.is_prerelease({"tag_name": tag}) is expected


def test_prereleases_do_not_double_report_their_final_release(github_stub):
    """v2.4.0 and v2.4.0rc1 carry the same notes; reporting both is noise."""
    notes = "- Removed the `foo()` helper"
    github_stub.reply([_release("v2.4.0rc1", notes), _release("v2.4.0", notes)])
    out = _changelog(github_stub, "2.3.0", "2.4.0")

    assert out["releases"] == 1
    assert [row[0] for row in unpack(out["packed"])] == ["v2.4.0"]


def test_prereleases_are_kept_when_they_are_the_only_evidence(github_stub):
    """Dropping them here would turn a real finding into a false all-clear."""
    github_stub.reply([_release("v2.4.0rc1", "BREAKING CHANGE: dropped `foo()`")])
    out = _changelog(github_stub, "2.3.0", "2.4.0")

    assert out["releases"] == 1
    assert out["checked"] is True
    assert out["breaking"] is True
    assert [row[0] for row in unpack(out["packed"])] == ["v2.4.0rc1"]


def test_a_match_starting_on_a_blank_line_still_quotes_real_text(github_stub):
    """`^\\s*` under re.M walks over newlines, so the match can begin on a
    blank line. The sample must be the list item, never the empty line."""
    github_stub.reply([_release("v2.0.0", "## Changes\n\n\n- Removed `foo()`\n")])
    out = _changelog(github_stub, "1.0.0", "2.0.0")

    samples = unpack(out["packed"])
    assert samples, "a removal in the notes must produce a sample"
    assert all(row[2].strip() for row in samples), "no empty sample lines"
    assert any("Removed `foo()`" in row[2] for row in samples)


def test_unreadable_notes_on_a_minor_bump_claim_nothing(github_stub):
    github_stub.reply({"message": "boom"}, status=500)
    out = _changelog(github_stub, "1.26.0", "1.28.0")

    assert out["checked"] is False
    assert out["breaking"] is False
    assert out["markers"] == ""                        # no evidence either way
    assert "HTTP 500" in out["warning"]


# --------------------------------------------------------------------------
# compute_verdict — the honesty invariant
# --------------------------------------------------------------------------

def _rec(name, **over):
    rec = {"ecosystem": "pypi", "name": name, "current": "1.0", "latest": "2.0",
           "gap": "major", "outdated": True, "direct": True, "files": 3,
           "checked": True, "breaking": True}
    rec.update(over)
    return rec


def test_records_can_come_from_a_file_instead_of_stdin(tmp_path):
    """A rote step has no TTY, so the file form is the one a Play can run."""
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [
        _rec("numpy"),
        _rec("scipy", direct=False, gap="minor"),
    ]) + "\n")

    out = json.loads(run("compute_verdict.py", str(path)).stdout)
    assert out["ok"] is True
    assert out["total"] == 2
    assert out["act"] == 1
    assert out["safe"] == 1
    assert [row[0] for row in unpack(out["packed"])] == ["ACT", "SAFE"]


def test_file_and_stdin_forms_agree(tmp_path):
    records = "\n".join(json.dumps(r) for r in [_rec("numpy"), _rec("scipy")]) + "\n"
    path = tmp_path / "records.jsonl"
    path.write_text(records)

    assert (json.loads(run("compute_verdict.py", str(path)).stdout)
            == json.loads(run("compute_verdict.py", stdin=records).stdout))


def test_an_unreadable_records_file_fails_closed(tmp_path):
    """Silently triaging zero dependencies would report a false all-clear."""
    proc = run("compute_verdict.py", str(tmp_path / "nope.jsonl"))
    assert proc.returncode == 2
    assert "cannot read" in proc.stderr
    assert proc.stdout == ""


def test_an_empty_file_is_an_honest_nothing_to_triage(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    out = json.loads(run("compute_verdict.py", str(path)).stdout)
    assert out["ok"] is True
    assert out["total"] == 0
    assert out["headline"] == "nothing to triage"



def _tier(direct, checked, breaking):
    rec = {"ecosystem": "npm", "name": "x", "current": "1.0.0", "latest": "2.0.0",
           "gap": "major", "outdated": True, "direct": direct, "files": 1,
           "checked": checked, "breaking": breaking}
    out = json.loads(run("compute_verdict.py", stdin=json.dumps(rec)).stdout)
    return unpack(out["packed"])[0][0]


@pytest.mark.parametrize("direct,checked,breaking",
                         list(itertools.product([True, False], repeat=3)))
def test_unreadable_notes_never_become_safe(direct, checked, breaking):
    """The invariant the whole tool rests on.

    If you import a package directly and nobody could read its release notes,
    the answer is REVIEW. Calling that SAFE would tell someone an upgrade is
    fine when it was never checked.
    """
    tier = _tier(direct, checked, breaking)
    if direct and not checked and not breaking:
        assert tier == "REVIEW"
    if direct and breaking:
        assert tier == "ACT"
    if not direct:
        assert tier == "SAFE"       # transitive: not your call site, not your problem


def test_current_versions_are_not_flagged():
    rec = {"name": "x", "outdated": False, "direct": True, "gap": "none"}
    out = json.loads(run("compute_verdict.py", stdin=json.dumps(rec)).stdout)
    assert out["current"] == 1 and out["act"] == 0


def test_ranking_puts_act_first():
    recs = [
        {"name": "safe-one", "outdated": True, "direct": False, "gap": "major",
         "checked": True, "breaking": True},
        {"name": "act-one", "outdated": True, "direct": True, "gap": "major",
         "checked": True, "breaking": True},
        {"name": "review-one", "outdated": True, "direct": True, "gap": "minor",
         "checked": False, "breaking": False},
    ]
    stdin = "\n".join(json.dumps(r) for r in recs)
    out = json.loads(run("compute_verdict.py", stdin=stdin).stdout)
    tiers = [row[0] for row in unpack(out["packed"])]
    assert tiers == ["ACT", "REVIEW", "SAFE"]
    assert out["headline"].startswith("1 of 3")


def test_empty_input_degrades():
    proc = run("compute_verdict.py", stdin="")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["total"] == 0


def test_malformed_input_is_a_hard_fault():
    proc = run("compute_verdict.py", stdin="not json\n")
    assert proc.returncode == 2
    assert "not valid JSON" in proc.stderr


# --------------------------------------------------------------------------
# find_callsites
# --------------------------------------------------------------------------

def test_python_import_line_numbers_are_exact(tmp_path):
    (tmp_path / "m.py").write_text(
        "from __future__ import annotations\n"    # 1
        "\n"                                      # 2
        "from dataclasses import dataclass\n"     # 3
        "\n"                                      # 4
        "import numpy as np\n"                    # 5
    )
    out = json.loads(run("find_callsites.py", str(tmp_path), "pypi", "numpy").stdout)
    rel, line, src = unpack(out["packed"])[0]
    assert line == "5", "a wrong line number destroys the tool's core promise"
    assert src == "import numpy as np"


def test_commented_out_imports_are_not_call_sites(tmp_path):
    src = tmp_path / "a.js"
    src.write_text(
        "// const x = require('jest');\n"
        "/* import jest from 'jest'; */\n"
        "const chalk = require('chalk');\n"
    )
    jest = json.loads(run("find_callsites.py", str(tmp_path), "npm", "jest").stdout)
    assert jest["direct"] is False, "a commented-out require is not a call site"

    chalk = json.loads(run("find_callsites.py", str(tmp_path), "npm", "chalk").stdout)
    assert chalk["direct"] is True


def test_live_import_still_counts_alongside_a_commented_one(tmp_path):
    (tmp_path / "a.js").write_text("// require('jest');\nconst j = require('jest');\n")
    out = json.loads(run("find_callsites.py", str(tmp_path), "npm", "jest").stdout)
    assert out["direct"] is True
    assert unpack(out["packed"])[0][1] == "2"


def test_scoped_and_subpath_npm_imports_match(tmp_path):
    (tmp_path / "a.ts").write_text(
        "import { debounce } from 'lodash/debounce';\n"
        "import x from '@scope/pkg';\n"
    )
    lodash = json.loads(run("find_callsites.py", str(tmp_path), "npm", "lodash").stdout)
    scoped = json.loads(run("find_callsites.py", str(tmp_path), "npm", "@scope/pkg").stdout)
    assert lodash["direct"] is True and scoped["direct"] is True


def test_rust_hyphen_names_match_underscore_imports(tmp_path):
    (tmp_path / "m.rs").write_text("use my_crate::Thing;\n")
    out = json.loads(run("find_callsites.py", str(tmp_path), "crates", "my-crate").stdout)
    assert out["direct"] is True


def test_uninstalled_package_is_reported_transitive(tmp_path):
    (tmp_path / "m.py").write_text("import os\n")
    out = json.loads(run("find_callsites.py", str(tmp_path), "pypi", "requests").stdout)
    assert out["direct"] is False
    assert "transitive" in out["note"]


def test_vendor_directories_are_skipped(tmp_path):
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "index.js").write_text("const x = require('express');\n")
    out = json.loads(run("find_callsites.py", str(tmp_path), "npm", "express").stdout)
    assert out["direct"] is False, "dependencies' own imports are not your call sites"


# --------------------------------------------------------------------------
# tools/inline_steps — the published Play must not point at one laptop
# --------------------------------------------------------------------------

def test_every_step_script_is_inlined():
    table = dict(inline_steps.steps())
    assert set(table) == {"compute_verdict", "fetch_changelog", "fetch_registry",
                          "find_callsites", "parse_manifest"}
    for prefix in table.values():
        assert prefix[0] == "python3" and prefix[1] == "-c"


def test_inlined_form_carries_no_local_path():
    """The whole point: nothing in the argv may reference this machine."""
    for name, prefix in inline_steps.steps():
        joined = " ".join(prefix)
        assert STEPS not in joined
        assert ".py" not in prefix[2], f"{name} still names a file"


@pytest.mark.parametrize("step,args", [
    ("parse_manifest", ["{root}"]),
    ("find_callsites", ["{root}", "pypi", "numpy"]),
])
def test_inlined_and_file_forms_agree(step, args, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["numpy==1.26"]\n')
    (tmp_path / "app.py").write_text("import numpy as np\n")
    filled = [a.format(root=str(tmp_path)) for a in args]

    direct = subprocess.run(
        [sys.executable, os.path.join(STEPS, f"{step}.py"), *filled],
        capture_output=True, text=True)
    inlined = subprocess.run(
        [*inline_steps.argv_prefix(os.path.join(STEPS, f"{step}.py")), *filled],
        capture_output=True, text=True)

    assert inlined.returncode == direct.returncode == 0
    assert json.loads(inlined.stdout) == json.loads(direct.stdout)


def test_inlined_form_preserves_a_failing_exit_code():
    """Fail-closed has to survive the transport, or REVIEW rows become SAFE."""
    prefix = inline_steps.argv_prefix(os.path.join(STEPS, "compute_verdict.py"))
    proc = subprocess.run([*prefix, "/nonexistent/records.jsonl"],
                          capture_output=True, text=True)
    assert proc.returncode == 2
    assert "cannot read" in proc.stderr
    assert proc.stdout == ""


# --------------------------------------------------------------------------
# The carrier chain — steps fed by value edges rather than a file on disk
#
# These are the tests that make the Play portable. Every stage takes the
# previous stage's output as one argv scalar, fills its own columns, and passes
# the rest through, so `compute_verdict` no longer reads a records file that
# only exists on the machine the Play was recorded on.
#
# The invariant tests below are the ones worth keeping: a stage that did not
# run must widen REVIEW. It must never produce SAFE or CURRENT.
# --------------------------------------------------------------------------

def carrier(**over):
    """A fully-populated carrier row, ACT by default."""
    row = {"eco": "pypi", "name": "numpy", "current": "1.26", "latest": "2.5.2",
           "repo": "numpy/numpy", "gap": "major", "outdated": "1", "direct": "1",
           "files": "14", "site": "tests/mocks.py:13", "checked": "1",
           "breaking": "1", "markers": "removal"}
    row.update(over)
    return FS.join([row["eco"], row["name"], row["current"], row["latest"],
                    row["repo"], row["gap"], row["outdated"], row["direct"],
                    row["files"], row["site"], row["checked"], row["breaking"],
                    row["markers"]])


def verdict(*rows):
    proc = run("compute_verdict.py", "--batch", json.dumps(
        {"ok": True, "packed": RS.join(rows)}))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def tiers(out):
    return {row[2]: row[0] for row in unpack(out["packed"])}


def test_short_carrier_rows_are_padded_not_dropped():
    """Stage 1 emits three columns; downstream must read the rest as unknown."""
    out = verdict(FS.join(["pypi", "numpy", "1.26"]))
    assert out["total"] == 1
    assert tiers(out) == {"numpy": "REVIEW"}


def test_batch_accepts_a_whole_payload_or_a_bare_packed_scalar():
    """The step must not care whether the edge resolves .stdout.text or .packed."""
    row = carrier()
    whole = run("compute_verdict.py", "--batch",
                json.dumps({"ok": True, "packed": row}))
    bare = run("compute_verdict.py", "--batch", row)
    assert whole.returncode == bare.returncode == 0
    assert json.loads(whole.stdout) == json.loads(bare.stdout)


def test_malformed_upstream_payload_is_a_hard_fault():
    """A broken edge must fail closed, not triage zero dependencies."""
    proc = run("compute_verdict.py", "--batch", '{"ok": true, "packed"')
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "will not parse" in proc.stderr


@pytest.mark.parametrize("script,args", [
    ("fetch_registry.py", ["--batch"]),
    ("fetch_changelog.py", ["--batch"]),
    ("compute_verdict.py", ["--batch"]),
])
def test_batch_without_a_payload_is_a_hard_fault(script, args):
    proc = run(script, *args)
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


@pytest.mark.parametrize("script,args", [
    ("fetch_registry.py", ["--batch", '{"ok": true, "packed": ""}']),
    ("fetch_changelog.py", ["--batch", '{"ok": true, "packed": ""}']),
    ("compute_verdict.py", ["--batch", '{"ok": true, "packed": ""}']),
])
def test_an_empty_upstream_degrades_rather_than_failing(script, args):
    """A repository with no dependencies is an expected absence, not an error."""
    proc = run(script, *args)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert "no depend" in out["warning"]


# --- the honesty invariant, one stage at a time ---------------------------

def test_a_skipped_registry_stage_reports_review_not_current():
    """Unknown 'outdated' must not read as 'already current'."""
    out = verdict(carrier(outdated="", latest="", gap="", checked="", breaking=""))
    assert tiers(out) == {"numpy": "REVIEW"}
    assert out["current"] == 0
    assert "never resolved" in unpack(out["packed"])[0][7]


def test_a_skipped_callsites_stage_reports_review_not_safe():
    """Unknown 'direct' must not read as 'transitive, bump it blind'."""
    out = verdict(carrier(direct="", files="", site=""))
    assert tiers(out) == {"numpy": "REVIEW"}
    assert out["safe"] == 0
    assert "never scanned" in unpack(out["packed"])[0][7]


def test_a_skipped_changelog_stage_reports_review_not_safe():
    """Unknown 'checked' must not read as 'notes read and clean'."""
    out = verdict(carrier(checked="", breaking="", markers=""))
    assert tiers(out) == {"numpy": "REVIEW"}
    assert out["safe"] == 0


def test_unread_notes_keep_their_markers_visible_in_review():
    """A major bump nobody could verify still says so, without becoming ACT."""
    out = verdict(carrier(checked="0", breaking="0", markers="major-version-bump"))
    row = unpack(out["packed"])[0]
    assert row[0] == "REVIEW"
    assert "major-version-bump" in row[7]


def test_every_unknown_at_once_is_review_never_safe():
    """The fully degraded run: nothing checked, nothing laundered."""
    out = verdict(FS.join(["pypi", "numpy", "1.26"]),
                  FS.join(["pypi", "scipy", "1.11"]))
    assert out["review"] == 2
    assert out["safe"] == out["current"] == out["act"] == 0


def test_a_clean_full_row_is_still_allowed_to_be_safe():
    """The invariant must not make SAFE unreachable — only unearned."""
    out = verdict(carrier(breaking="0", markers=""))
    assert tiers(out) == {"numpy": "SAFE"}


# --- the stages fill their own columns ------------------------------------

def test_registry_batch_fills_its_columns_and_keeps_the_others_blank():
    """Uses an unsupported ecosystem so the plumbing is tested without a network."""
    proc = run("fetch_registry.py", "--batch",
               json.dumps({"ok": True, "packed": FS.join(["cpan", "Moose", "2.0"])}))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["count"] == 1 and out["unresolved"] == 1
    assert "unsupported ecosystem" in out["warning"]
    row = unpack(out["packed"])[0]
    assert row[:2] == ["cpan", "Moose"]
    assert row[6] == "0"                       # outdated: known false, not blank
    assert row[7] == row[10] == row[11] == ""  # downstream columns untouched


def test_callsites_batch_fills_direct_files_and_first_site(tmp_path):
    (tmp_path / "app.py").write_text("import numpy as np\n")
    upstream = json.dumps({"ok": True, "packed": RS.join([
        carrier(direct="", files="", site=""),
        carrier(name="scipy", direct="", files="", site=""),
    ])})
    proc = run("find_callsites.py", "--batch", str(tmp_path), upstream)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["direct"] == 1
    numpy_row, scipy_row = unpack(out["packed"])
    assert numpy_row[7] == "1" and numpy_row[8] == "1"
    assert numpy_row[9] == "app.py:1"
    assert scipy_row[7] == "0" and scipy_row[9] == ""
    assert numpy_row[3] == "2.5.2"             # upstream columns passed through


def test_changelog_batch_reads_notes_and_skips_current_packages(github_stub):
    github_stub.reply([_release("v2.0.0", "- Removed the old API.")])
    upstream = json.dumps({"ok": True, "packed": RS.join([
        carrier(current="1.0", latest="2.0.0", checked="", breaking="", markers=""),
        carrier(name="scipy", outdated="0", checked="", breaking="", markers=""),
    ])})
    proc = run("fetch_changelog.py", "--batch", upstream, env=github_stub.env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["count"] == 2 and out["considered"] == 1
    numpy_row, scipy_row = unpack(out["packed"])
    assert numpy_row[10] == "1" and numpy_row[11] == "1"
    assert "removal" in numpy_row[12]
    assert scipy_row[10] == ""                 # already current; nothing to read


def test_rate_limited_changelog_batch_produces_review_never_safe(github_stub):
    """The degraded run the whole design exists to get right."""
    github_stub.reply({"message": "rate limited"}, status=403,
                      headers={"X-RateLimit-Remaining": "0"})
    upstream = json.dumps({"ok": True, "packed": RS.join([
        carrier(gap="minor", latest="1.18.1", checked="", breaking="", markers=""),
    ])})
    proc = run("fetch_changelog.py", "--batch", upstream, env=github_stub.env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["rate_limited"] == 1
    assert "GITHUB_TOKEN" in out["warning"]

    final = verdict(*[RS.join(unpack(out["packed"])[0]).replace(RS, FS)])
    assert tiers(final) == {"numpy": "REVIEW"}
    assert final["safe"] == 0


def test_the_chain_runs_with_nothing_on_disk_but_the_project(tmp_path, github_stub):
    """End to end, no records file: exactly what a stranger's machine has."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["numpy==1.26"]\n')
    (tmp_path / "app.py").write_text("import numpy as np\n")
    github_stub.reply([_release("v2.0.0", "- Removed the old API.")])

    step1 = run("parse_manifest.py", str(tmp_path))
    assert step1.returncode == 0, step1.stderr
    # Stage 2 needs a live registry, so the version facts are supplied here the
    # way it would supply them; every other stage is the real thing.
    resolved = json.dumps({"ok": True, "packed": FS.join(
        ["pypi", "numpy", "1.26", "2.0.0", "numpy/numpy", "major", "1"])})

    step3 = run("find_callsites.py", "--batch", str(tmp_path), resolved)
    assert step3.returncode == 0, step3.stderr
    step4 = run("fetch_changelog.py", "--batch", step3.stdout, env=github_stub.env)
    assert step4.returncode == 0, step4.stderr
    step5 = run("compute_verdict.py", "--batch", step4.stdout)
    assert step5.returncode == 0, step5.stderr

    out = json.loads(step5.stdout)
    assert out["act"] == 1
    assert "breaking changes in code you actually call" in out["headline"]
    assert unpack(out["packed"])[0][8] == "app.py:1"


def test_delimiters_survive_the_inlined_transport(tmp_path):
    """Carrier rows travel through argv; FS and RS must arrive intact."""
    payload = json.dumps({"ok": True, "packed": RS.join([carrier(), carrier(name="scipy")])})
    prefix = inline_steps.argv_prefix(os.path.join(STEPS, "compute_verdict.py"))
    inlined = subprocess.run([*prefix, "--batch", payload],
                             capture_output=True, text=True)
    direct = run("compute_verdict.py", "--batch", payload)
    assert inlined.returncode == direct.returncode == 0, inlined.stderr
    assert json.loads(inlined.stdout) == json.loads(direct.stdout)
    assert json.loads(inlined.stdout)["act"] == 2


# --- the rendered report --------------------------------------------------

def test_report_lists_every_row_under_the_headline():
    out = verdict(carrier(), carrier(name="requests", direct="0", files="0", site=""))
    report = out["report"]
    assert report.startswith(out["headline"])
    assert "numpy" in report and "requests" in report
    assert "1.26 -> 2.5.2" in report
    assert "tests/mocks.py:13" in report
    assert "not imported directly" in report


def test_report_of_an_empty_run_is_just_the_headline():
    proc = run("compute_verdict.py", "--batch", '{"ok": true, "packed": ""}')
    out = json.loads(proc.stdout)
    assert out["report"] == out["headline"] == "nothing to triage"


def test_report_says_review_when_nothing_could_be_checked():
    """The degraded run has to read as degraded, not as an all-clear."""
    out = verdict(carrier(checked="", breaking="", markers=""))
    assert "REVIEW" in out["report"]
    assert "SAFE" not in out["report"]


# --------------------------------------------------------------------------
# The generated Play
# --------------------------------------------------------------------------

def test_the_published_play_is_not_stale():
    """main.ts carries the step scripts as base64, so a step change that is
    tested here but never regenerated ships a Play that does something else."""
    proc = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(HERE), "tools", "build_play.py"),
         "--check"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def _play():
    with open(os.path.join(os.path.dirname(HERE), "play", "main.ts")) as handle:
        return handle.read()


def test_the_play_carries_no_local_path():
    """Criterion 2: it has to run for someone who is not the author.

    The scripts are embedded as source, so their own filenames appear in usage
    strings -- that is fine. What must not appear is a path into a machine.
    """
    play = _play()
    for local in ("/home/adity", "/home/user", "next-step-26", "steps/",
                  os.path.dirname(HERE)):
        assert local not in play, f"main.ts still references {local}"


def test_the_play_declares_a_real_description_and_one_parameter():
    play = _play()
    assert 'description: ""' not in play
    assert "- name: root" in play
    assert "*/" not in play.split("---\n */")[0].replace("/**", "", 1)


def test_every_step_in_the_play_has_a_readable_name():
    """python3_7 teaches an inspecting judge nothing."""
    play = _play()
    for name in ("find_dependencies", "resolve_versions", "locate_callsites",
                 "read_changelogs", "rank_verdict"):
        assert f" *   {name}:" in play
    assert "python3_" not in play


def test_changelog_batch_says_why_it_could_not_read(github_stub):
    """"checked: 0" alone does not tell you whether to set a token or a repo."""
    github_stub.reply({"message": "forbidden"}, status=403)
    upstream = json.dumps({"ok": True, "packed": RS.join([
        carrier(checked="", breaking="", markers=""),
        carrier(name="scipy", repo="", checked="", breaking="", markers=""),
    ])})
    proc = run("fetch_changelog.py", "--batch", upstream, env=github_stub.env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["checked"] == 0 and out["unread"] == 2
    assert "HTTP 403" in out["warning"]
    assert "no GitHub repository known" in out["warning"]


def test_the_play_frontmatter_parses_and_wires_the_chain():
    """The generator claims the YAML is valid; this is the independent check."""
    yaml = pytest.importorskip("yaml")
    play = _play()
    inner = play.split("/**\n", 1)[1].split("\n */\n", 1)[0]
    stripped = "\n".join(
        line[3:] if line.startswith(" * ") else line[2:] if line.startswith(" *") else line
        for line in inner.split("\n"))
    doc = yaml.safe_load(stripped.split("---\n", 1)[1].rsplit("---", 1)[0])

    order = ["find_dependencies", "resolve_versions", "locate_callsites",
             "read_changelogs", "rank_verdict"]
    assert list(doc["steps"]) == order
    assert [p["name"] for p in doc["parameters"]] == ["root"]

    # Every stage but the first is fed by an edge onto the one before it, and
    # the two that take a path are given the parameter. That wiring is the
    # whole reason compute_verdict no longer reads a file from disk.
    for earlier, later in zip(order, order[1:]):
        argv = doc["steps"][later]["argv"]
        assert doc["steps"][later]["depends_on"] == [earlier]
        assert any(a.startswith(f"@{earlier}{{") for a in argv[3:]), later
    assert "$root" in doc["steps"]["find_dependencies"]["argv"]
    assert "$root" in doc["steps"]["locate_callsites"]["argv"]


def test_the_embedded_scripts_are_the_scripts_on_disk():
    """base64 or source, the Play must carry what the tests exercised."""
    yaml = pytest.importorskip("yaml")
    play = _play()
    inner = play.split("/**\n", 1)[1].split("\n */\n", 1)[0]
    stripped = "\n".join(
        line[3:] if line.startswith(" * ") else line[2:] if line.startswith(" *") else line
        for line in inner.split("\n"))
    doc = yaml.safe_load(stripped.split("---\n", 1)[1].rsplit("---", 1)[0])

    for step, script in [("find_dependencies", "parse_manifest"),
                         ("resolve_versions", "fetch_registry"),
                         ("locate_callsites", "find_callsites"),
                         ("read_changelogs", "fetch_changelog"),
                         ("rank_verdict", "compute_verdict")]:
        with open(os.path.join(STEPS, f"{script}.py")) as handle:
            on_disk = handle.read().rstrip("\n")
        embedded = doc["steps"][step]["argv"][2].lstrip("\n").rstrip("\n")
        if embedded.startswith("import base64;exec("):
            blob = embedded.split("'")[1]
            embedded = base64.b64decode(blob).decode("utf-8").rstrip("\n")
        assert embedded == on_disk, f"{step} does not carry steps/{script}.py"
