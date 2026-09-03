#!/usr/bin/env -S rote play run
/**
 * Upgrade Impact Triage
 *
 * Of your outdated dependencies, which ones will actually break you.
 *
 * @rote-frontmatter
 * ---
 * name: upgrade-impact-triage
 * version: 0.1.0
 * description: "Of your outdated dependencies, which ones ship breaking changes in code you actually import? Reads every manifest under root, resolves current versus latest from npm, PyPI or crates.io, reads the GitHub release notes between the two, and finds the files and line numbers that import each package. Ranks each dependency ACT (breaking changes, and you call it directly), REVIEW (you call it, but the notes could not be read), SAFE (transitive, or the notes were read and were clean) or CURRENT. An unreadable changelog reports as REVIEW and never as SAFE, so a rate-limited or offline run produces more rows to check by hand and never fewer warnings. Standard library Python only; GITHUB_TOKEN is optional and raises the API rate limit."
 * source: https://semver.org/
 * provenance:
 *   author: adityagaur <adityagaur12077@gmail.com>
 *   tier: local
 *   workspace: upgrade-impact-triage
 * metadata:
 *   rote_version: "0.78.0"
 *   version: "0.1.0"
 *   status: draft
 *   kind: atomic
 *   flow_type: parallel
 *   execution_model: steps_with_presentation
 *   format: typescript
 *   requires_endpoints: []
 *   requires_sessions: false
 *   discoverability:
 *     tags:
 *     - domain-software-development
 *     - software-development
 *     - job-dependency-upgrade
 *     - tool-package-registry
 *     - tool-github
 *     - effect-read-only
 * parameters:
 * - name: root
 *   param_type: string
 *   required: false
 *   default: '.'
 *   description: Path to the project to triage; defaults to the current directory
 *   example: .
 *   valid_values: null
 * contract:
 *   atomic: true
 *   input:
 *     type: none
 *   output:
 *     format: json
 *     destination: stdout
 *   composable: true
 * steps:
 *   find_dependencies:
 *     type: process.exec
 *     timeout_ms: 30000
 *     argv:
 *     - python3
 *     - -c
 *     - |2
 *
 *       #!/usr/bin/env python3
 *       """Step 1 — find dependency manifests under a root and emit one flat dependency list.
 *
 *       Contract (rote step):
 *         stdout is data (one JSON object), exit status is the failure signal.
 *         Expected absence -> {"ok": true, "warning": ...} exit 0.
 *         Hard fault       -> message on stderr, exit 2.
 *
 *       Collections cross step boundaries as a delimited scalar, because value-edge jq
 *       must resolve to a scalar. Records are RS-separated, fields FS-separated:
 *         ecosystem FS name FS current_spec
 *       """
 *       import json
 *       import os
 *       import re
 *       import sys
 *
 *       FS = chr(31)
 *       RS = chr(30)
 *
 *       SKIP_DIRS = {
 *           ".git", "node_modules", "venv", ".venv", "__pycache__", "target",
 *           "dist", "build", ".tox", ".mypy_cache", "site-packages", ".next",
 *       }
 *
 *
 *       def die(msg):
 *           print(f"parse_manifest: {msg}", file=sys.stderr)
 *           raise SystemExit(2)
 *
 *
 *       def emit(payload):
 *           sys.stdout.write(json.dumps(payload) + "\n")
 *           raise SystemExit(0)
 *
 *
 *       def clean_version(spec):
 *           """Strip range operators to a bare version. '^1.2.3' -> '1.2.3'."""
 *           if not isinstance(spec, str):
 *               return ""
 *           m = re.search(r"(\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.\-]+)?)", spec)
 *           return m.group(1) if m else ""
 *
 *
 *       def from_package_json(path):
 *           with open(path, encoding="utf-8") as fh:
 *               data = json.load(fh)
 *           out = []
 *           for field in ("dependencies", "devDependencies"):
 *               for name, spec in (data.get(field) or {}).items():
 *                   # Skip non-registry specs: file:, link:, git+, workspace:, npm alias
 *                   if isinstance(spec, str) and re.match(r"^(file:|link:|git|https?:|workspace:|npm:)", spec):
 *                       continue
 *                   out.append(("npm", name, clean_version(spec)))
 *           return out
 *
 *
 *       def from_pyproject(path):
 *           try:
 *               import tomllib
 *           except ModuleNotFoundError:
 *               return []
 *           with open(path, "rb") as fh:
 *               data = tomllib.load(fh)
 *           out = []
 *           project = data.get("project") or {}
 *           for entry in project.get("dependencies") or []:
 *               name = re.split(r"[<>=!~\[; ]", entry.strip(), maxsplit=1)[0]
 *               if name:
 *                   out.append(("pypi", name, clean_version(entry)))
 *           poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
 *           for name, spec in poetry.items():
 *               if name.lower() == "python":
 *                   continue
 *               if isinstance(spec, dict):
 *                   spec = spec.get("version", "")
 *               out.append(("pypi", name, clean_version(spec)))
 *           return out
 *
 *
 *       def from_requirements(path):
 *           out = []
 *           with open(path, encoding="utf-8") as fh:
 *               for line in fh:
 *                   line = line.split("#", 1)[0].strip()
 *                   if not line or line.startswith("-"):
 *                       continue
 *                   name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
 *                   if name:
 *                       out.append(("pypi", name, clean_version(line)))
 *           return out
 *
 *
 *       def from_cargo(path):
 *           try:
 *               import tomllib
 *           except ModuleNotFoundError:
 *               return []
 *           with open(path, "rb") as fh:
 *               data = tomllib.load(fh)
 *           out = []
 *           for field in ("dependencies", "dev-dependencies"):
 *               for name, spec in (data.get(field) or {}).items():
 *                   if isinstance(spec, dict):
 *                       if "path" in spec or "git" in spec:
 *                           continue
 *                       spec = spec.get("version", "")
 *                   out.append(("crates", name, clean_version(spec)))
 *           return out
 *
 *
 *       READERS = {
 *           "package.json": from_package_json,
 *           "pyproject.toml": from_pyproject,
 *           "requirements.txt": from_requirements,
 *           "Cargo.toml": from_cargo,
 *       }
 *
 *
 *       def main():
 *           root = sys.argv[1] if len(sys.argv) > 1 else "."
 *           if not os.path.isdir(root):
 *               die(f"root is not a directory: {root}")
 *
 *           deps, seen, manifests, unreadable = [], set(), [], []
 *           for dirpath, dirnames, filenames in os.walk(root):
 *               dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
 *               for fname in filenames:
 *                   reader = READERS.get(fname)
 *                   if not reader:
 *                       continue
 *                   full = os.path.join(dirpath, fname)
 *                   try:
 *                       found = reader(full)
 *                   except Exception as exc:                      # noqa: BLE001
 *                       unreadable.append(f"{os.path.relpath(full, root)}: {exc}")
 *                       continue
 *                   manifests.append(os.path.relpath(full, root))
 *                   for eco, name, ver in found:
 *                       key = (eco, name.lower())
 *                       if key in seen:
 *                           continue
 *                       seen.add(key)
 *                       deps.append((eco, name, ver))
 *
 *           if not manifests:
 *               if unreadable:
 *                   warning = "every manifest found failed to parse: " + "; ".join(unreadable)
 *               else:
 *                   warning = f"no supported manifest found under {root}"
 *               emit({
 *                   "ok": True, "warning": warning,
 *                   "count": 0, "packed": "", "manifests": "", "ecosystems": "",
 *               })
 *
 *           packed = RS.join(FS.join([e, n, v]) for e, n, v in deps)
 *           payload = {
 *               "ok": True,
 *               "count": len(deps),
 *               "packed": packed,
 *               "manifests": ",".join(sorted(manifests)),
 *               "ecosystems": ",".join(sorted({e for e, _, _ in deps})),
 *           }
 *           if unreadable:
 *               payload["warning"] = "; ".join(unreadable)
 *           emit(payload)
 *
 *
 *       if __name__ == "__main__":
 *           main()
 *     - "$root"
 *   resolve_versions:
 *     type: process.exec
 *     timeout_ms: 180000
 *     depends_on:
 *     - find_dependencies
 *     argv:
 *     - python3
 *     - -c
 *     - |2
 *
 *       #!/usr/bin/env python3
 *       """Step 2 — one dependency, one registry reading.
 *
 *       Runs once per dependency under `for_each`. Answers: what is the latest version,
 *       how big is the gap, and where does its source live (so the changelog step can
 *       find release notes).
 *
 *       Contract (rote step):
 *         Network trouble or an unknown package is an EXPECTED ABSENCE -> ok:true with a
 *         warning, exit 0, so one dead package cannot kill a 47-dependency report.
 *         Only a malformed invocation is a hard fault -> stderr, exit 2.
 *
 *       Uses only the standard library, so deps.toml declares python3 and nothing else.
 *       """
 *       import json
 *       import re
 *       import sys
 *       import time
 *       import urllib.error
 *       import urllib.request
 *
 *       FS = chr(31)
 *       RS = chr(30)
 *       UA = "upgrade-impact-triage/0.1 (+https://play.modiqo.ai)"
 *       TIMEOUT = 20
 *
 *
 *       def die(msg):
 *           print(f"fetch_registry: {msg}", file=sys.stderr)
 *           raise SystemExit(2)
 *
 *
 *       def emit(payload):
 *           sys.stdout.write(json.dumps(payload) + "\n")
 *           raise SystemExit(0)
 *
 *
 *       def get_json(url, attempts=3):
 *           """GET JSON with a User-Agent. crates.io answers 403 without one."""
 *           last = ""
 *           for i in range(attempts):
 *               req = urllib.request.Request(url, headers={
 *                   "User-Agent": UA, "Accept": "application/json",
 *               })
 *               try:
 *                   with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
 *                       return json.loads(resp.read().decode("utf-8")), ""
 *               except urllib.error.HTTPError as exc:
 *                   if exc.code == 404:
 *                       return None, "not found in registry"
 *                   last = f"HTTP {exc.code}"
 *                   if exc.code in (429, 500, 502, 503, 504):
 *                       time.sleep(1.5 * (i + 1))
 *                       continue
 *                   return None, last
 *               except Exception as exc:                          # noqa: BLE001
 *                   last = str(exc)
 *                   time.sleep(1.0 * (i + 1))
 *           return None, last or "unreachable"
 *
 *
 *       def parse_version(v):
 *           parts = re.findall(r"\d+", v or "")
 *           return [int(p) for p in parts[:3]] + [0] * (3 - len(parts[:3]))
 *
 *
 *       def is_prerelease(v):
 *           return bool(re.search(r"[-+](alpha|beta|rc|dev|pre|a\d|b\d)", str(v), re.I))
 *
 *
 *       def gap_between(cur, new):
 *           if not cur or not new:
 *               return "unknown"
 *           c, n = parse_version(cur), parse_version(new)
 *           if n == c:
 *               return "none"
 *           if n < c:
 *               return "ahead"
 *           if n[0] != c[0]:
 *               return "major"
 *           if n[1] != c[1]:
 *               return "minor"
 *           return "patch"
 *
 *
 *       def norm_repo(url):
 *           """Normalise a repository field to owner/name on GitHub, else ''.
 *
 *           Anchors on the FIRST two path segments after the host: a tracker URL such as
 *           github.com/numpy/numpy/issues must resolve to numpy/numpy, never numpy/issues.
 *           """
 *           if not isinstance(url, str):
 *               return ""
 *           m = re.search(
 *               r"github\.com[:/]+([^/\s#?]+)/([^/\s#?]+?)(?:\.git)?(?:[/#?]|$)",
 *               url.strip(),
 *           )
 *           if not m:
 *               return ""
 *           owner, name = m.group(1), m.group(2)
 *           if owner.lower() in ("sponsors", "orgs", "apps", "settings"):
 *               return ""
 *           return f"{owner}/{name}"
 *
 *
 *       def repo_from_urls(project_urls, *fallbacks):
 *           """Find a source repo among PyPI project_urls.
 *
 *           Keys are author-supplied and their case varies ('source' for numpy,
 *           'Source Code' for others), so match case-insensitively on a priority list
 *           before scanning every value for any GitHub URL.
 *           """
 *           urls = {str(k).strip().lower(): v for k, v in (project_urls or {}).items()}
 *           for key in ("source", "source code", "repository", "code", "github", "homepage", "home"):
 *               found = norm_repo(urls.get(key))
 *               if found:
 *                   return found
 *           for value in urls.values():                 # any GitHub URL beats nothing
 *               found = norm_repo(value)
 *               if found:
 *                   return found
 *           for value in fallbacks:
 *               found = norm_repo(value)
 *               if found:
 *                   return found
 *           return ""
 *
 *
 *       def npm(name):
 *           data, err = get_json(f"https://registry.npmjs.org/{urllib.request.quote(name, safe='@')}")
 *           if data is None:
 *               return None, err
 *           latest = ((data.get("dist-tags") or {}).get("latest")) or ""
 *           repo = (data.get("repository") or {})
 *           repo_url = repo.get("url") if isinstance(repo, dict) else repo
 *           return {"latest": latest, "repo": norm_repo(repo_url)}, ""
 *
 *
 *       def pypi(name):
 *           data, err = get_json(f"https://pypi.org/pypi/{urllib.request.quote(name)}/json")
 *           if data is None:
 *               return None, err
 *           info = data.get("info") or {}
 *           repo = repo_from_urls(info.get("project_urls"), info.get("home_page"))
 *           return {"latest": info.get("version") or "", "repo": repo}, ""
 *
 *
 *       def crates(name):
 *           data, err = get_json(f"https://crates.io/api/v1/crates/{urllib.request.quote(name)}")
 *           if data is None:
 *               return None, err
 *           crate = data.get("crate") or {}
 *           repo = norm_repo(crate.get("repository"))
 *           return {"latest": crate.get("max_stable_version") or crate.get("newest_version") or "",
 *                   "repo": repo}, ""
 *
 *
 *       FETCHERS = {"npm": npm, "pypi": pypi, "crates": crates}
 *
 *
 *       # ---------------------------------------------------------------------------
 *       # Carrier record — how dependency facts cross a step boundary.
 *       #
 *       # Each stage fills its own columns and passes the rest through, so the whole
 *       # triage runs as a linear DAG wired by value edges. No stage needs a file on
 *       # disk, and no stage needs to know how many dependencies there are.
 *       #
 *       #   0 ecosystem   3 latest   6 outdated   9  first_site  12 markers
 *       #   1 name        4 repo     7 direct     10 checked
 *       #   2 current     5 gap      8 files      11 breaking
 *       #
 *       # Booleans are "1" / "0" when known and "" when the stage that fills them has
 *       # not run. That third state is load-bearing: an unfilled column must read as
 *       # UNKNOWN downstream, never as a clean bill of health.
 *       # ---------------------------------------------------------------------------
 *       COLS = 13
 *
 *
 *       def scrub(value):
 *           """Field text can never contain the delimiters that frame it."""
 *           return str(value).replace(FS, " ").replace(RS, " ")
 *
 *
 *       def unpack(packed):
 *           """Carrier rows, padded to COLS. Short rows come from an earlier stage."""
 *           rows = []
 *           for chunk in (packed or "").split(RS):
 *               if chunk:
 *                   rows.append((chunk.split(FS) + [""] * COLS)[:COLS])
 *           return rows
 *
 *
 *       def repack(rows):
 *           return RS.join(FS.join(scrub(col) for col in row) for row in rows)
 *
 *
 *       def upstream_packed(arg):
 *           """The previous step's output, however the value edge chose to deliver it.
 *
 *           A whole stdout payload (a JSON object) and a bare `packed` scalar are both
 *           accepted, so the step does not depend on whether the edge resolves
 *           `.stdout.text` or `.stdout.json.packed`.
 *           """
 *           text = (arg or "").strip()
 *           if not text.startswith("{"):
 *               return text
 *           try:
 *               doc = json.loads(text)
 *           except json.JSONDecodeError as exc:
 *               die(f"upstream payload will not parse as JSON: {exc}")
 *           if not isinstance(doc, dict):
 *               die("upstream payload is not a JSON object")
 *           return doc.get("packed", "")
 *
 *
 *       def resolve(eco, name, current):
 *           """One dependency, one registry reading.
 *
 *           Never raises: a remote problem is an expected absence carried in the
 *           payload, so one dead package cannot kill a 47-dependency report.
 *           """
 *           fetcher = FETCHERS.get(eco)
 *           base = {"ok": True, "ecosystem": eco, "name": name, "current": current,
 *                   "latest": "", "repo": "", "gap": "unknown", "outdated": False}
 *
 *           if not fetcher:
 *               base["warning"] = f"unsupported ecosystem: {eco}"
 *               return base
 *
 *           facts, err = fetcher(name)
 *           if facts is None:
 *               base["warning"] = f"{name}: {err}"
 *               return base
 *
 *           latest = facts["latest"]
 *           gap = gap_between(current, latest)
 *           base.update({
 *               "latest": latest,
 *               "repo": facts["repo"],
 *               "gap": gap,
 *               "outdated": gap in ("major", "minor", "patch"),
 *               "prerelease": is_prerelease(latest),
 *           })
 *           if not facts["repo"]:
 *               base["warning"] = f"{name}: no GitHub source URL published; changelog unavailable"
 *           return base
 *
 *
 *       def run_batch(arg):
 *           """Resolve every dependency the manifest step found, in one step.
 *
 *           Fills carrier columns 2-6 (current, latest, repo, gap, outdated) and leaves
 *           everything else for the stages downstream.
 *           """
 *           rows = unpack(upstream_packed(arg))
 *           if not rows:
 *               emit({"ok": True, "warning": "no dependencies on input", "count": 0,
 *                     "resolved": 0, "outdated": 0, "packed": ""})
 *
 *           warnings = []
 *           for row in rows:
 *               rec = resolve(row[0], row[1], row[2])
 *               if rec.get("warning"):
 *                   warnings.append(rec["warning"])
 *               row[2] = rec["current"]
 *               row[3] = rec["latest"]
 *               row[4] = rec["repo"]
 *               row[5] = rec["gap"]
 *               row[6] = "1" if rec["outdated"] else "0"
 *
 *           payload = {
 *               "ok": True,
 *               "count": len(rows),
 *               "resolved": len(rows) - len(warnings),
 *               "outdated": sum(1 for row in rows if row[6] == "1"),
 *               "packed": repack(rows),
 *           }
 *           if warnings:
 *               payload["unresolved"] = len(warnings)
 *               payload["warning"] = "; ".join(warnings[:5])
 *           emit(payload)
 *
 *
 *       def main():
 *           if len(sys.argv) > 1 and sys.argv[1] == "--batch":
 *               if len(sys.argv) < 3:
 *                   die("usage: fetch_registry.py --batch <upstream payload>")
 *               run_batch(sys.argv[2])
 *
 *           if len(sys.argv) < 3:
 *               die("usage: fetch_registry.py <ecosystem> <name> [current_version]\n"
 *                   "   or: fetch_registry.py --batch <upstream payload>")
 *           emit(resolve(sys.argv[1], sys.argv[2],
 *                        sys.argv[3] if len(sys.argv) > 3 else ""))
 *
 *
 *       if __name__ == "__main__":
 *           main()
 *     - "--batch"
 *     - "@find_dependencies{$.stdout.text | fromjson | .packed}"
 *   locate_callsites:
 *     type: process.exec
 *     timeout_ms: 90000
 *     depends_on:
 *     - resolve_versions
 *     argv:
 *     - python3
 *     - -c
 *     - |2
 *
 *       #!/usr/bin/env python3
 *       """Step 4 — does this project actually import the package, and where?
 *
 *       This is the step that separates the Play from Dependabot. A breaking change in
 *       a dependency you never import directly is not your problem; the same change in
 *       one you call on line 42 is.
 *
 *       Contract (rote step):
 *         Never a hard fault for "not found" — a package with no call sites is a REAL
 *         ANSWER, not an absence. Only a bad invocation or unreadable root exits 2.
 *
 *       Standard library only. Walks the tree once rather than shelling out, so no
 *       ripgrep dependency lands in deps.toml.
 *       """
 *       import json
 *       import os
 *       import re
 *       import sys
 *
 *       FS = chr(31)
 *       RS = chr(30)
 *
 *       MAX_BYTES = 1_500_000        # skip anything bigger; it is not hand-written source
 *       MAX_HITS = 40
 *
 *       SKIP_DIRS = {
 *           ".git", "node_modules", "venv", ".venv", "__pycache__", "target", "dist",
 *           "build", ".tox", ".mypy_cache", "site-packages", ".next", "vendor",
 *           "coverage", ".pytest_cache", ".ruff_cache", "htmlcov",
 *       }
 *
 *       EXTS = {
 *           "npm":    {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".svelte", ".vue"},
 *           "pypi":   {".py", ".pyi"},
 *           "crates": {".rs"},
 *       }
 *
 *
 *       def die(msg):
 *           print(f"find_callsites: {msg}", file=sys.stderr)
 *           raise SystemExit(2)
 *
 *
 *       def emit(payload):
 *           sys.stdout.write(json.dumps(payload) + "\n")
 *           raise SystemExit(0)
 *
 *
 *       def import_aliases(eco, name):
 *           """Plausible module names for a distribution name.
 *
 *           Distribution name and import name often differ (PyPI beautifulsoup4 imports
 *           as bs4). We cannot resolve that from the registry alone, so we try the
 *           mechanical transforms and report honestly when nothing matches.
 *           """
 *           base = name.strip()
 *           out = {base}
 *           if eco == "pypi":
 *               out.add(base.replace("-", "_"))
 *               out.add(base.replace("-", ""))
 *               out.add(base.replace("_", "-"))
 *               if base.lower().startswith("python-"):
 *                   out.add(base[7:].replace("-", "_"))
 *           elif eco == "crates":
 *               out.add(base.replace("-", "_"))
 *           elif eco == "npm":
 *               out.add(base)                       # scoped names like @scope/pkg stay whole
 *           return {a for a in out if a}
 *
 *
 *       def patterns_for(eco, aliases):
 *           pats = []
 *           for alias in aliases:
 *               q = re.escape(alias)
 *               if eco == "npm":
 *                   pats.append(re.compile(
 *                       rf"""(?:require\s*\(\s*['"]{q}(?:/[^'"]*)?['"]\s*\)"""
 *                       rf"""|from\s+['"]{q}(?:/[^'"]*)?['"]"""
 *                       rf"""|import\s*\(\s*['"]{q}(?:/[^'"]*)?['"]\s*\))"""))
 *               elif eco == "pypi":
 *                   # [ \t]* not \s* — under re.M, \s matches newlines, so the match would
 *                   # start on an earlier blank line and report the wrong line number.
 *                   pats.append(re.compile(
 *                       rf"^[ \t]*(?:from\s+{q}(?:\.\w+)*\s+import\s+|import\s+{q}(?:\.\w+)*)",
 *                       re.M))
 *               elif eco == "crates":
 *                   pats.append(re.compile(
 *                       rf"(?:^[ \t]*use\s+{q}\s*(?:::|;)|^[ \t]*extern\s+crate\s+{q}\b)", re.M))
 *           return pats
 *
 *
 *       COMMENT_PREFIXES = ("//", "*", "/*", "#")
 *
 *
 *       def is_commented(line):
 *           """True when the matched line is a whole-line comment.
 *
 *           The Python and Rust patterns anchor with ^[ \\t]* so a leading # or // already
 *           prevents a match. The npm pattern cannot anchor — require() legitimately
 *           appears mid-line — so a commented-out require would otherwise be reported as
 *           a live call site and inflate the count this Play exists to shrink.
 *           """
 *           return line.lstrip().startswith(COMMENT_PREFIXES)
 *
 *
 *       # ---------------------------------------------------------------------------
 *       # Carrier record — how dependency facts cross a step boundary.
 *       #
 *       # Each stage fills its own columns and passes the rest through, so the whole
 *       # triage runs as a linear DAG wired by value edges. No stage needs a file on
 *       # disk, and no stage needs to know how many dependencies there are.
 *       #
 *       #   0 ecosystem   3 latest   6 outdated   9  first_site  12 markers
 *       #   1 name        4 repo     7 direct     10 checked
 *       #   2 current     5 gap      8 files      11 breaking
 *       #
 *       # Booleans are "1" / "0" when known and "" when the stage that fills them has
 *       # not run. That third state is load-bearing: an unfilled column must read as
 *       # UNKNOWN downstream, never as a clean bill of health.
 *       # ---------------------------------------------------------------------------
 *       COLS = 13
 *
 *
 *       def scrub(value):
 *           """Field text can never contain the delimiters that frame it."""
 *           return str(value).replace(FS, " ").replace(RS, " ")
 *
 *
 *       def unpack(packed):
 *           """Carrier rows, padded to COLS. Short rows come from an earlier stage."""
 *           rows = []
 *           for chunk in (packed or "").split(RS):
 *               if chunk:
 *                   rows.append((chunk.split(FS) + [""] * COLS)[:COLS])
 *           return rows
 *
 *
 *       def repack(rows):
 *           return RS.join(FS.join(scrub(col) for col in row) for row in rows)
 *
 *
 *       def upstream_packed(arg):
 *           """The previous step's output, however the value edge chose to deliver it.
 *
 *           A whole stdout payload (a JSON object) and a bare `packed` scalar are both
 *           accepted, so the step does not depend on whether the edge resolves
 *           `.stdout.text` or `.stdout.json.packed`.
 *           """
 *           text = (arg or "").strip()
 *           if not text.startswith("{"):
 *               return text
 *           try:
 *               doc = json.loads(text)
 *           except json.JSONDecodeError as exc:
 *               die(f"upstream payload will not parse as JSON: {exc}")
 *           if not isinstance(doc, dict):
 *               die("upstream payload is not a JSON object")
 *           return doc.get("packed", "")
 *
 *
 *       def scan(root, eco, name):
 *           """Where, if anywhere, this project imports the package.
 *
 *           "Not found" is a real answer, not an absence, so this never raises; only a
 *           bad invocation or an unreadable root is a hard fault, and that is checked
 *           once by the caller.
 *           """
 *           exts = EXTS.get(eco)
 *           base = {"ok": True, "ecosystem": eco, "name": name,
 *                   "direct": False, "hits": 0, "files": 0, "packed": "", "scanned": 0}
 *           if not exts:
 *               base["warning"] = f"no source pattern for ecosystem: {eco}"
 *               return base
 *
 *           aliases = import_aliases(eco, name)
 *           pats = patterns_for(eco, aliases)
 *
 *           hits, files_with, scanned, unreadable = [], set(), 0, 0
 *           for dirpath, dirnames, filenames in os.walk(root):
 *               dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
 *               for fname in filenames:
 *                   if os.path.splitext(fname)[1] not in exts:
 *                       continue
 *                   full = os.path.join(dirpath, fname)
 *                   try:
 *                       if os.path.getsize(full) > MAX_BYTES:
 *                           continue
 *                       with open(full, encoding="utf-8", errors="replace") as fh:
 *                           text = fh.read()
 *                   except OSError:
 *                       unreadable += 1
 *                       continue
 *                   scanned += 1
 *                   lines = text.splitlines()
 *                   for pat in pats:
 *                       for m in pat.finditer(text):
 *                           line_no = text.count("\n", 0, m.start()) + 1
 *                           raw = lines[line_no - 1] if line_no <= len(lines) else ""
 *                           if is_commented(raw):
 *                               continue              # a commented-out import is not a call site
 *                           rel = os.path.relpath(full, root)
 *                           files_with.add(rel)
 *                           if len(hits) < MAX_HITS:
 *                               hits.append((rel, str(line_no), raw.strip()[:160]))
 *                           break                     # one live hit per pattern per file is enough
 *
 *           base.update({
 *               "direct": bool(files_with),
 *               "hits": len(hits),
 *               "files": len(files_with),
 *               "scanned": scanned,
 *               "packed": RS.join(FS.join(h) for h in hits),
 *           })
 *           if not files_with:
 *               base["note"] = (f"{name} is not imported directly in {scanned} scanned "
 *                               f"source files — likely transitive")
 *           if unreadable:
 *               base["warning"] = f"{unreadable} file(s) could not be read"
 *           return base
 *
 *
 *       def run_batch(root, arg):
 *           """Scan the tree once per dependency, filling carrier columns 7-9.
 *
 *           first_site is the representative call site quoted in the final report; it
 *           is the reason a row reads "breaking, and you call it here" rather than
 *           "breaking, somewhere".
 *           """
 *           rows = unpack(upstream_packed(arg))
 *           if not rows:
 *               emit({"ok": True, "warning": "no dependencies on input", "count": 0,
 *                     "direct": 0, "scanned": 0, "packed": ""})
 *
 *           scanned = 0
 *           for row in rows:
 *               rec = scan(root, row[0], row[1])
 *               scanned = max(scanned, rec["scanned"])
 *               row[7] = "1" if rec["direct"] else "0"
 *               row[8] = str(rec["files"])
 *               first = rec["packed"].split(RS)[0] if rec["packed"] else ""
 *               if first:
 *                   parts = first.split(FS)
 *                   row[9] = f"{parts[0]}:{parts[1]}" if len(parts) > 1 else parts[0]
 *
 *           emit({
 *               "ok": True,
 *               "count": len(rows),
 *               "direct": sum(1 for row in rows if row[7] == "1"),
 *               "scanned": scanned,
 *               "packed": repack(rows),
 *           })
 *
 *
 *       def main():
 *           if len(sys.argv) > 1 and sys.argv[1] == "--batch":
 *               if len(sys.argv) < 4:
 *                   die("usage: find_callsites.py --batch <root> <upstream payload>")
 *               root = sys.argv[2]
 *               if not os.path.isdir(root):
 *                   die(f"root is not a directory: {root}")
 *               run_batch(root, sys.argv[3])
 *
 *           if len(sys.argv) < 4:
 *               die("usage: find_callsites.py <root> <ecosystem> <name>\n"
 *                   "   or: find_callsites.py --batch <root> <upstream payload>")
 *           root, eco, name = sys.argv[1], sys.argv[2], sys.argv[3]
 *           if not os.path.isdir(root):
 *               die(f"root is not a directory: {root}")
 *           emit(scan(root, eco, name))
 *
 *
 *       if __name__ == "__main__":
 *           main()
 *     - "--batch"
 *     - "$root"
 *     - "@resolve_versions{$.stdout.text | fromjson | .packed}"
 *   read_changelogs:
 *     type: process.exec
 *     timeout_ms: 240000
 *     depends_on:
 *     - locate_callsites
 *     argv:
 *     - python3
 *     - -c
 *     - |2
 *
 *       #!/usr/bin/env python3
 *       """Step 3 — read release notes between two versions and judge them breaking.
 *
 *       Contract (rote step):
 *         Every remote problem is an EXPECTED ABSENCE -> ok:true, exit 0.
 *
 *         The honesty rule that matters most here: when we cannot read the notes, the
 *         answer is "unknown", never "no breaking changes". A false negative here tells
 *         someone an upgrade is safe when nobody checked. `breaking` is only false when
 *         notes were actually read and contained no breaking markers; `checked` says
 *         which of those two situations you are in.
 *
 *       GITHUB_API_BASE overrides the API root (default https://api.github.com) for
 *       GitHub Enterprise installs and for hermetic tests of the success path.
 *
 *       Rate limit: the GitHub REST API allows 60 unauthenticated requests per hour,
 *       and a 47-dependency project blows through that. Set GITHUB_TOKEN to raise it to
 *       5000/hr. The token is optional by design so the Play still runs with no
 *       credentials at all -- it simply reports more "unknown" rows without one.
 *       """
 *       import json
 *       import os
 *       import re
 *       import sys
 *       import urllib.error
 *       import urllib.parse
 *       import urllib.request
 *
 *       FS = chr(31)
 *       RS = chr(30)
 *       UA = "upgrade-impact-triage/0.1 (+https://play.modiqo.ai)"
 *       TIMEOUT = 25
 *
 *
 *       def api_base():
 *           """Read at call time, not import time, so tests can point it at a stub."""
 *           return (os.environ.get("GITHUB_API_BASE", "").strip()
 *                   or "https://api.github.com").rstrip("/")
 *
 *       BREAKING_PATTERNS = [
 *           (re.compile(r"\bBREAKING[ -]CHANGES?\b", re.I), "breaking-change"),
 *           (re.compile(r"^[ \t]*#{1,4}[ \t]*breaking\b", re.I | re.M), "breaking-heading"),
 *           (re.compile(r"\bbackwards?[- ]incompatible\b", re.I), "incompatible"),
 *           (re.compile(r"^[ \t]*[-*][ \t]*\*{0,2}(removed?|dropped?)\*{0,2}\s+", re.I | re.M), "removal"),
 *           (re.compile(r"\brenamed?\b.{0,40}\bto\b", re.I), "rename"),
 *           (re.compile(r"\bno longer\b", re.I), "no-longer"),
 *           (re.compile(r"\bmigration guide\b", re.I), "migration-guide"),
 *       ]
 *
 *
 *       # GitHub's `prerelease` flag is author-set and often left false on rc tags,
 *       # so the tag itself is the more reliable signal. Requires digits around the
 *       # marker so "v1.2.3-abc" is not read as an alpha.
 *       PRERELEASE_TAG = re.compile(
 *           r"\d(?:[-._]?(?:rc|alpha|beta|dev|pre)\d*|(?:a|b|rc)\d+)\b", re.I)
 *
 *
 *       def is_prerelease(rel):
 *           return bool(rel.get("prerelease")
 *                       or PRERELEASE_TAG.search(str(rel.get("tag_name") or "")))
 *
 *
 *       def first_line(text, pos):
 *           """The first non-blank line at or after `pos`.
 *
 *           A match can begin on a blank line, so the text at `pos` is not always the
 *           line worth quoting. Never return an empty sample.
 *           """
 *           for line in text[pos:pos + 400].splitlines():
 *               if line.strip():
 *                   return line.strip()
 *           return ""
 *
 *
 *       def die(msg):
 *           print(f"fetch_changelog: {msg}", file=sys.stderr)
 *           raise SystemExit(2)
 *
 *
 *       def emit(payload):
 *           sys.stdout.write(json.dumps(payload) + "\n")
 *           raise SystemExit(0)
 *
 *
 *       def parse_version(v):
 *           parts = re.findall(r"\d+", str(v) or "")
 *           return tuple(int(p) for p in parts[:3]) + (0,) * (3 - len(parts[:3]))
 *
 *
 *       def tag_version(tag):
 *           """Pull a version tuple out of a release tag such as v1.2.3 or rel-1.2.3."""
 *           m = re.search(r"(\d+(?:\.\d+){0,2})", str(tag) or "")
 *           return parse_version(m.group(1)) if m else None
 *
 *
 *       def get_json(url):
 *           """Return (data, error, rate_limited)."""
 *           headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
 *           token = os.environ.get("GITHUB_TOKEN", "").strip()
 *           if token:
 *               headers["Authorization"] = f"Bearer {token}"
 *           req = urllib.request.Request(url, headers=headers)
 *           try:
 *               with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
 *                   return json.loads(resp.read().decode("utf-8")), "", False
 *           except urllib.error.HTTPError as exc:
 *               remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
 *               if exc.code in (403, 429) and remaining == "0":
 *                   return None, "GitHub API rate limit reached (set GITHUB_TOKEN to raise it)", True
 *               if exc.code == 404:
 *                   return None, "no releases published for this repository", False
 *               return None, f"HTTP {exc.code}", False
 *           except Exception as exc:                              # noqa: BLE001
 *               return None, str(exc), False
 *
 *
 *       # ---------------------------------------------------------------------------
 *       # Carrier record — how dependency facts cross a step boundary.
 *       #
 *       # Each stage fills its own columns and passes the rest through, so the whole
 *       # triage runs as a linear DAG wired by value edges. No stage needs a file on
 *       # disk, and no stage needs to know how many dependencies there are.
 *       #
 *       #   0 ecosystem   3 latest   6 outdated   9  first_site  12 markers
 *       #   1 name        4 repo     7 direct     10 checked
 *       #   2 current     5 gap      8 files      11 breaking
 *       #
 *       # Booleans are "1" / "0" when known and "" when the stage that fills them has
 *       # not run. That third state is load-bearing: an unfilled column must read as
 *       # UNKNOWN downstream, never as a clean bill of health.
 *       # ---------------------------------------------------------------------------
 *       COLS = 13
 *
 *
 *       def scrub(value):
 *           """Field text can never contain the delimiters that frame it."""
 *           return str(value).replace(FS, " ").replace(RS, " ")
 *
 *
 *       def unpack(packed):
 *           """Carrier rows, padded to COLS. Short rows come from an earlier stage."""
 *           rows = []
 *           for chunk in (packed or "").split(RS):
 *               if chunk:
 *                   rows.append((chunk.split(FS) + [""] * COLS)[:COLS])
 *           return rows
 *
 *
 *       def repack(rows):
 *           return RS.join(FS.join(scrub(col) for col in row) for row in rows)
 *
 *
 *       def upstream_packed(arg):
 *           """The previous step's output, however the value edge chose to deliver it.
 *
 *           A whole stdout payload (a JSON object) and a bare `packed` scalar are both
 *           accepted, so the step does not depend on whether the edge resolves
 *           `.stdout.text` or `.stdout.json.packed`.
 *           """
 *           text = (arg or "").strip()
 *           if not text.startswith("{"):
 *               return text
 *           try:
 *               doc = json.loads(text)
 *           except json.JSONDecodeError as exc:
 *               die(f"upstream payload will not parse as JSON: {exc}")
 *           if not isinstance(doc, dict):
 *               die("upstream payload is not a JSON object")
 *           return doc.get("packed", "")
 *
 *
 *       def read_notes(repo, current, latest):
 *           """Read the release notes between two versions and judge them breaking.
 *
 *           Never raises: every remote problem is an expected absence. When the notes
 *           cannot be read the answer is `checked: false` — "unknown" — and never
 *           `breaking: false`.
 *           """
 *           base = {
 *               "ok": True, "repo": repo, "current": current, "latest": latest,
 *               "checked": False,          # were release notes actually read?
 *               "breaking": False,         # only meaningful when checked is true
 *               "releases": 0, "markers": "", "packed": "",
 *           }
 *
 *           cur_v, new_v = parse_version(current), parse_version(latest)
 *
 *           if not repo or "/" not in repo:
 *               base["warning"] = "no GitHub repository known; cannot read release notes"
 *               if new_v[0] > cur_v[0]:
 *                   base["markers"] = "major-version-bump"
 *                   base["note"] = "unread notes, but a major version bump implies breaking changes"
 *               return base
 *
 *           data, err, limited = get_json(
 *               f"{api_base()}/repos/{urllib.parse.quote(repo)}/releases?per_page=100")
 *           if data is None:
 *               base["warning"] = f"{repo}: {err}"
 *               base["rate_limited"] = limited
 *               # Major bumps are breaking by semver convention even when notes are unreadable.
 *               if new_v[0] > cur_v[0]:
 *                   base["markers"] = "major-version-bump"
 *                   base["note"] = "unread notes, but a major version bump implies breaking changes"
 *               return base
 *
 *           candidates = []
 *           for rel in data:
 *               if rel.get("draft"):
 *                   continue
 *               tv = tag_version(rel.get("tag_name"))
 *               if tv is None or not (cur_v < tv <= new_v):
 *                   continue
 *               candidates.append(rel)
 *
 *           # A release candidate's notes are superseded by the final release's, so
 *           # counting both reports every finding twice (v2.4.0 and v2.4.0rc1 with
 *           # identical text). Drop prereleases -- unless they are all there is, in
 *           # which case they are the only evidence available and dropping them would
 *           # turn a real finding into a false "nothing to read".
 *           stable = [rel for rel in candidates if not is_prerelease(rel)]
 *           in_range = stable or candidates
 *
 *           markers, samples = set(), []
 *           for rel in in_range:
 *               body = rel.get("body") or ""
 *               for pat, label in BREAKING_PATTERNS:
 *                   m = pat.search(body)
 *                   if m:
 *                       markers.add(label)
 *                       line = first_line(body, m.start())
 *                       if line and len(samples) < 12:
 *                           samples.append((str(rel.get("tag_name") or "?"), label, line[:150]))
 *
 *           base.update({
 *               "checked": True,
 *               "releases": len(in_range),
 *               "breaking": bool(markers),
 *               "markers": ",".join(sorted(markers)),
 *               "packed": RS.join(FS.join(s) for s in samples),
 *           })
 *
 *           if not in_range:
 *               base["checked"] = False
 *               base["warning"] = (f"{repo}: no releases found between {current} and {latest} "
 *                                  f"(project may use tags or a CHANGELOG file instead)")
 *               if new_v[0] > cur_v[0]:
 *                   base["markers"] = "major-version-bump"
 *           elif new_v[0] > cur_v[0] and not markers:
 *               base["breaking"] = True
 *               base["markers"] = "major-version-bump"
 *               base["note"] = "no breaking wording in notes, but the major version changed"
 *
 *           return base
 *
 *
 *       def run_batch(arg):
 *           """Read notes for every outdated dependency, filling carrier columns 10-12.
 *
 *           Dependencies already at the latest version are skipped: their columns stay
 *           empty, which downstream reads as CURRENT rather than as a verdict. Nothing
 *           here can turn an unread changelog into a clean one — a rate-limited run
 *           leaves `checked` at "0" and produces more REVIEW rows, never fewer ACT rows.
 *           """
 *           rows = unpack(upstream_packed(arg))
 *           if not rows:
 *               emit({"ok": True, "warning": "no dependencies on input", "count": 0,
 *                     "checked": 0, "breaking": 0, "packed": ""})
 *
 *           checked = breaking = limited = skipped = 0
 *           warnings = []
 *           for row in rows:
 *               if row[6] != "1":                     # not outdated; nothing to compare
 *                   skipped += 1
 *                   continue
 *               rec = read_notes(row[4], row[2], row[3])
 *               if rec.get("rate_limited"):
 *                   limited += 1
 *               elif rec.get("warning"):
 *                   warnings.append(rec["warning"])
 *               row[10] = "1" if rec["checked"] else "0"
 *               row[11] = "1" if rec["breaking"] else "0"
 *               row[12] = rec["markers"]
 *               checked += bool(rec["checked"])
 *               breaking += bool(rec["breaking"])
 *
 *           payload = {
 *               "ok": True,
 *               "count": len(rows),
 *               "considered": len(rows) - skipped,
 *               "checked": checked,
 *               "breaking": breaking,
 *               "packed": repack(rows),
 *           }
 *           if limited:
 *               payload["rate_limited"] = limited
 *               payload["warning"] = (f"{limited} changelog(s) unread: GitHub API rate limit "
 *                                     f"reached. Set GITHUB_TOKEN to raise it to 5000/hr; "
 *                                     f"until then these report as REVIEW, not SAFE.")
 *           elif warnings:
 *               # "checked: 0" on its own says nothing about why. A 403, an unknown
 *               # repository and a project that tags instead of releasing all degrade to
 *               # REVIEW, and they are not the same problem to fix.
 *               payload["unread"] = len(warnings)
 *               payload["warning"] = "; ".join(warnings[:5])
 *           emit(payload)
 *
 *
 *       def main():
 *           if len(sys.argv) > 1 and sys.argv[1] == "--batch":
 *               if len(sys.argv) < 3:
 *                   die("usage: fetch_changelog.py --batch <upstream payload>")
 *               run_batch(sys.argv[2])
 *
 *           if len(sys.argv) < 4:
 *               die("usage: fetch_changelog.py <owner/repo> <current_version> <latest_version>\n"
 *                   "   or: fetch_changelog.py --batch <upstream payload>")
 *           emit(read_notes(sys.argv[1], sys.argv[2], sys.argv[3]))
 *
 *
 *       if __name__ == "__main__":
 *           main()
 *     - "--batch"
 *     - "@locate_callsites{$.stdout.text | fromjson | .packed}"
 *   rank_verdict:
 *     type: process.exec
 *     timeout_ms: 15000
 *     depends_on:
 *     - read_changelogs
 *     argv:
 *     - python3
 *     - -c
 *     - |2
 *
 *       #!/usr/bin/env python3
 *       """Step 5 — join registry, changelog and call-site facts into a ranked verdict.
 *
 *       Reads one JSON object per line, each merging what the earlier steps learned
 *       about a single dependency, and emits the canonical result. Input comes from a
 *       file when a path is given and from stdin otherwise -- a rote step has no TTY,
 *       so the file form is what makes this capturable and runnable as a step.
 *
 *       The ranking rule, and the reason the Play is worth running:
 *
 *         ACT      breaking changes AND you import it directly.       -> your problem, today
 *         REVIEW   you import it directly, but breaking status is
 *                  UNKNOWN because notes could not be read.           -> nobody checked; you decide
 *         SAFE     outdated, but you never import it directly, or
 *                  the notes were read and were clean.                -> bump it blind
 *         CURRENT  already at the latest version.
 *
 *       REVIEW exists so an unreadable changelog can never be laundered into "safe".
 *       A rate-limited run reports more REVIEW rows; it never reports fewer ACT rows.
 *       """
 *       import json
 *       import sys
 *
 *       FS = chr(31)
 *       RS = chr(30)
 *
 *       ORDER = {"ACT": 0, "REVIEW": 1, "SAFE": 2, "CURRENT": 3}
 *       GAP_WEIGHT = {"major": 0, "minor": 1, "patch": 2, "none": 3, "unknown": 4, "ahead": 5}
 *
 *
 *       def die(msg):
 *           print(f"compute_verdict: {msg}", file=sys.stderr)
 *           raise SystemExit(2)
 *
 *
 *       # ---------------------------------------------------------------------------
 *       # Carrier record — how dependency facts cross a step boundary.
 *       #
 *       # Each stage fills its own columns and passes the rest through, so the whole
 *       # triage runs as a linear DAG wired by value edges. No stage needs a file on
 *       # disk, and no stage needs to know how many dependencies there are.
 *       #
 *       #   0 ecosystem   3 latest   6 outdated   9  first_site  12 markers
 *       #   1 name        4 repo     7 direct     10 checked
 *       #   2 current     5 gap      8 files      11 breaking
 *       #
 *       # Booleans are "1" / "0" when known and "" when the stage that fills them has
 *       # not run. That third state is load-bearing: an unfilled column must read as
 *       # UNKNOWN downstream, never as a clean bill of health.
 *       # ---------------------------------------------------------------------------
 *       COLS = 13
 *
 *
 *       def scrub(value):
 *           """Field text can never contain the delimiters that frame it."""
 *           return str(value).replace(FS, " ").replace(RS, " ")
 *
 *
 *       def unpack(packed):
 *           """Carrier rows, padded to COLS. Short rows come from an earlier stage."""
 *           rows = []
 *           for chunk in (packed or "").split(RS):
 *               if chunk:
 *                   rows.append((chunk.split(FS) + [""] * COLS)[:COLS])
 *           return rows
 *
 *
 *       def repack(rows):
 *           return RS.join(FS.join(scrub(col) for col in row) for row in rows)
 *
 *
 *       def upstream_packed(arg):
 *           """The previous step's output, however the value edge chose to deliver it.
 *
 *           A whole stdout payload (a JSON object) and a bare `packed` scalar are both
 *           accepted, so the step does not depend on whether the edge resolves
 *           `.stdout.text` or `.stdout.json.packed`.
 *           """
 *           text = (arg or "").strip()
 *           if not text.startswith("{"):
 *               return text
 *           try:
 *               doc = json.loads(text)
 *           except json.JSONDecodeError as exc:
 *               die(f"upstream payload will not parse as JSON: {exc}")
 *           if not isinstance(doc, dict):
 *               die("upstream payload is not a JSON object")
 *           return doc.get("packed", "")
 *
 *
 *       def emit(payload):
 *           sys.stdout.write(json.dumps(payload) + "\n")
 *           raise SystemExit(0)
 *
 *
 *       def classify(rec):
 *           # An unfilled fact is UNKNOWN, never a clean bill of health. A stage that
 *           # did not run must widen REVIEW; it must never narrow it, because the whole
 *           # value of this Play is that "safe to bump" means somebody checked.
 *           if rec.get("outdated_unknown"):
 *               return "REVIEW", "version never resolved; status unknown"
 *           if not rec.get("outdated"):
 *               return "CURRENT", "already current"
 *           if rec.get("direct_unknown"):
 *               return "REVIEW", "call sites never scanned; status unknown"
 *
 *           direct = bool(rec.get("direct"))
 *           checked = bool(rec.get("checked"))
 *           breaking = bool(rec.get("breaking"))
 *
 *           if not direct:
 *               return "SAFE", "not imported directly; transitive"
 *           if breaking:
 *               return "ACT", rec.get("markers") or "breaking changes in range"
 *           if not checked:
 *               why = rec.get("warning") or "release notes unavailable; status unknown"
 *               # Markers found without reading the notes -- a major version bump -- are
 *               # still evidence. Surfacing them keeps a degraded row informative
 *               # without promoting it out of REVIEW.
 *               if rec.get("markers"):
 *                   why = f"{why} ({rec['markers']})"
 *               return "REVIEW", why
 *           return "SAFE", "notes read, no breaking markers"
 *
 *
 *       def record_from_row(row):
 *           """A carrier row as the record classify() expects, unknowns preserved."""
 *           return {
 *               "ecosystem": row[0],
 *               "name": row[1],
 *               "current": row[2],
 *               "latest": row[3],
 *               "gap": row[5] or "unknown",
 *               "outdated": row[6] == "1",
 *               "outdated_unknown": row[6] == "",
 *               "direct": row[7] == "1",
 *               "direct_unknown": row[7] == "",
 *               "files": int(row[8]) if row[8].isdigit() else 0,
 *               "first_site": row[9],
 *               "checked": row[10] == "1",
 *               "breaking": row[11] == "1",
 *               "markers": row[12],
 *           }
 *
 *
 *       def read_records():
 *           """Records from --batch, from a named file, or from stdin.
 *
 *           --batch is the form the Play uses: the upstream step's output arrives whole
 *           as one argv scalar, so nothing has to exist on disk and the chain works on a
 *           machine that has never seen this repository.
 *           """
 *           argv = sys.argv[1:]
 *           if argv and argv[0] == "--batch":
 *               if len(argv) < 2:
 *                   die("usage: compute_verdict.py --batch <upstream payload>")
 *               return [record_from_row(row) for row in unpack(upstream_packed(argv[1]))]
 *
 *           stream, opened = None, False
 *           if argv:
 *               try:
 *                   stream, opened = open(argv[0], encoding="utf-8"), True
 *               except OSError as exc:
 *                   # A named file that cannot be read is a broken invocation, not an
 *                   # expected absence: failing closed beats triaging zero dependencies
 *                   # and reporting "nothing to triage".
 *                   die(f"cannot read {argv[0]}: {exc}")
 *           else:
 *               stream = sys.stdin
 *
 *           records = []
 *           for line_no, line in enumerate(stream, 1):
 *               line = line.strip()
 *               if not line:
 *                   continue
 *               try:
 *                   records.append(json.loads(line))
 *               except json.JSONDecodeError as exc:
 *                   die(f"line {line_no} is not valid JSON: {exc}")
 *           if opened:
 *               stream.close()
 *           return records
 *
 *
 *       def render(rows, headline):
 *           """A plain-text report, built here rather than in the Play body.
 *
 *           The Play's presentation layer has one job -- print this string -- so the
 *           formatting is covered by the same tests as the ranking it presents.
 *           """
 *           if not rows:
 *               return headline
 *           width = {
 *               "name": max(len(r["name"]) for r in rows),
 *               "ver": max(len(f'{r["current"] or "-"} -> {r["latest"] or "-"}') for r in rows),
 *               "gap": max(len(r["gap"]) for r in rows),
 *           }
 *           lines = [headline, ""]
 *           for r in rows:
 *               versions = f'{r["current"] or "-"} -> {r["latest"] or "-"}'
 *               files = f'{r["files"]} file' + ("s" if r["files"] != 1 else "")
 *               lines.append(
 *                   f'  {r["tier"]:<7} {r["ecosystem"]:<6} {r["name"]:<{width["name"]}}  '
 *                   f'{versions:<{width["ver"]}}  {r["gap"]:<{width["gap"]}}  '
 *                   f'{files:>8}  {r["site"] or "-"}'.rstrip())
 *               lines.append(f'  {"":<7} {r["why"]}')
 *           return "\n".join(lines)
 *
 *
 *       def main():
 *           records = read_records()
 *
 *           if not records:
 *               emit({
 *                   "ok": True, "warning": "no dependency records on input",
 *                   "total": 0, "act": 0, "review": 0, "safe": 0, "current": 0,
 *                   "headline": "nothing to triage", "report": "nothing to triage",
 *                   "packed": "",
 *               })
 *
 *           rows = []
 *           for rec in records:
 *               tier, why = classify(rec)
 *               rows.append({
 *                   "tier": tier,
 *                   "ecosystem": rec.get("ecosystem", "?"),
 *                   "name": rec.get("name", "?"),
 *                   "current": rec.get("current", ""),
 *                   "latest": rec.get("latest", ""),
 *                   "gap": rec.get("gap", "unknown"),
 *                   "direct": bool(rec.get("direct")),
 *                   "files": rec.get("files", 0),
 *                   "why": why,
 *                   "site": rec.get("first_site", ""),
 *               })
 *
 *           rows.sort(key=lambda r: (ORDER[r["tier"]], GAP_WEIGHT.get(r["gap"], 9), r["name"]))
 *           counts = {t: sum(1 for r in rows if r["tier"] == t) for t in ORDER}
 *           outdated = counts["ACT"] + counts["REVIEW"] + counts["SAFE"]
 *
 *           if counts["ACT"]:
 *               headline = (f"{counts['ACT']} of {len(rows)} dependencies have breaking changes "
 *                           f"in code you actually call")
 *           elif counts["REVIEW"]:
 *               headline = (f"no confirmed breaking changes, but {counts['REVIEW']} "
 *                           f"could not be verified")
 *           elif outdated:
 *               headline = f"{outdated} outdated, none of them breaking for your code"
 *           else:
 *               headline = "everything current"
 *
 *           packed = RS.join(FS.join([
 *               r["tier"], r["ecosystem"], r["name"], r["current"] or "-", r["latest"] or "-",
 *               r["gap"], str(r["files"]), r["why"], r["site"],
 *           ]) for r in rows)
 *
 *           emit({
 *               "ok": True,
 *               "report": render(rows, headline),
 *               "total": len(rows),
 *               "act": counts["ACT"], "review": counts["REVIEW"],
 *               "safe": counts["SAFE"], "current": counts["CURRENT"],
 *               "outdated": outdated,
 *               "headline": headline,
 *               "packed": packed,
 *           })
 *
 *
 *       if __name__ == "__main__":
 *           main()
 *     - "--batch"
 *     - "@read_changelogs{$.stdout.text | fromjson | .packed}"
 * ---
 */

const { FlowOutput, loadPresentationContext, stepName } =
  await import("__ROTE_PRESENTATION_SDK__");

type StageRow = { stage: string; label: string; state: string; note: string };
type Verdict = {
  total: number; act: number; review: number; safe: number; current: number;
  headline: string; report: string; warning?: string;
};

const out = new FlowOutput();
const ctx = await loadPresentationContext();

const STAGES: Array<[string, string]> = [
  ["find_dependencies", "manifests"],
  ["resolve_versions", "registry"],
  ["locate_callsites", "call sites"],
  ["read_changelogs", "release notes"],
  ["rank_verdict", "verdict join"],
];
const STEP_HANDLES = {
  find_dependencies: ctx.step(stepName("find_dependencies")),
  resolve_versions: ctx.step(stepName("resolve_versions")),
  locate_callsites: ctx.step(stepName("locate_callsites")),
  read_changelogs: ctx.step(stepName("read_changelogs")),
  rank_verdict: ctx.step(stepName("rank_verdict")),
};

const bodyOf = (step: (typeof STEP_HANDLES)[keyof typeof STEP_HANDLES]): Record<string, unknown> | null => {
  const outcome = step.outcome;
  if (outcome.status !== "completed" && outcome.status !== "restored") return null;
  const text = (outcome.output.body as { stdout?: { text?: string } })?.stdout?.text;
  if (typeof text !== "string" || !text.trim()) return null;
  try {
    const parsed = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
};

// The ledger is not decoration. When a stage degrades -- a rate-limited
// changelog read, an unreachable registry -- the rows it fed report REVIEW
// rather than SAFE, and this is where you see why.
const ledger: StageRow[] = [];
for (const [id, label] of STAGES) {
  const step = STEP_HANDLES[id as keyof typeof STEP_HANDLES];
  const info = bodyOf(step);
  const status = step.outcome.status;
  let state: string;
  let note = "";
  if (info && (status === "completed" || status === "restored")) {
    const degraded = typeof info["warning"] === "string";
    state = degraded ? "degraded" : "ok";
    note = degraded ? String(info["warning"]) : "";
  } else if (status === "completed" || status === "restored") {
    state = "degraded";
    note = "unparseable output";
  } else if (status === "skipped" || status === "blocked") {
    state = status;
    note = String((step.outcome.output as { reason?: string }).reason ?? "");
  } else {
    state = "failed";
    note = String((step.outcome.output as { message?: string }).message ?? "").slice(0, 80);
  }
  ledger.push({ stage: id, label, state, note });
}

const GLYPH: Record<string, string> = {
  ok: "████████",
  degraded: "█████░░░",
  skipped: "░░░░░░░░",
  blocked: "░░░░░░░░",
  failed: "░░░░░░░░",
};

const fallback: Verdict = {
  total: 0, act: 0, review: 0, safe: 0, current: 0,
  headline: "no verdict",
  report: "The verdict join did not produce a report; see the stage ledger.",
};
const verdictBody = bodyOf(STEP_HANDLES.rank_verdict);
const verdict: Verdict =
  verdictBody && typeof verdictBody["report"] === "string"
    ? (verdictBody as unknown as Verdict)
    : fallback;

const okCount = ledger.filter((r) => r.state === "ok").length;
const bar = "█".repeat(Math.round((okCount / ledger.length) * 24)).padEnd(24, "░");

const lines: string[] = [];
lines.push(`UPGRADE IMPACT  ${String(ctx.params.root ?? ".")}`);
lines.push("");
lines.push(`  stages  ${bar}  ${okCount}/${ledger.length} ok`);
for (const row of ledger) {
  lines.push(`  ${GLYPH[row.state] ?? GLYPH.failed}  ${row.label.padEnd(16)}${row.state}${row.note ? ` — ${row.note}` : ""}`);
}
lines.push("");
lines.push(verdict.report);
lines.push("");
lines.push("ACT = breaking changes in code you import directly. REVIEW = you import it,");
lines.push("but the release notes could not be read, so nobody has checked. An unreadable");
lines.push("changelog is never reported as SAFE.");

out.human(lines.join("\n"));
out.summary(verdict.headline);
out.result({ run_id: ctx.run.run_id, stages: ledger, ...verdict });
