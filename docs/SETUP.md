# Machine setup

Status: **rote is not yet installed.** The first attempt failed and rolled itself back.

## What went wrong the first time

The playoffs installer detected a `codex` binary and tried to configure it. That binary is the
**Windows** npm install, reachable from WSL only because WSL appends the Windows PATH into the
Linux one. It is a shim whose job is to exec `node`, and there is no `node` inside the distro:

```
- Codex: command failed (/mnt/c/Users/adity/AppData/Roaming/npm/codex
  plugin marketplace list --json):
  /mnt/c/Users/adity/AppData/Roaming/npm/codex: 15: exec: node: not found
```

Harness-connect failed, verification failed, and the installer rolled everything back —
`UPDATE FAILED — PREVIOUS VERSION RESTORED`. That is the safety mechanism working. Nothing is
damaged and nothing was installed.

This is not a rote bug. It is WSL interop: a Windows-installed CLI appearing on the Linux PATH
while being unusable there.

## The fix

> **Do not pass `--harness codex`.** An earlier draft of this plan said
> `--harness codex --harness claude`. Including codex is precisely what fails — the Windows shim
> is still there and still cannot exec node.

```bash
# 1. confirm the diagnosis
which -a codex node claude
#    expect: codex under /mnt/c/..., node and claude resolving to nothing

# 2. install Claude Code natively — it needs no Node, which is why it sidesteps this
curl -fsSL https://claude.ai/install.sh | bash
exec $SHELL -l

which claude            # MUST print /home/adity/.local/bin/claude, not /mnt/c/...
claude --version
claude doctor

# 3. authenticate: launch once, follow the browser prompts, exit
claude

# 4. re-run the playoffs installer pinned to that harness alone
curl -fsSL https://getrote.dev/playoffs/install.sh | sh -s -- --harness claude

# 5. verify
rote whoami             # ok: <email>

# 6. restart the harness, then
/play
/play run hello
```

## If it still fails

**Stop Windows PATH leaking into WSL.** The clean structural fix:

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[interop]
appendWindowsPath = false
EOF
```

Then from **PowerShell**, not WSL: `wsl --shutdown`, and reopen Ubuntu. Trade-off: Windows tools
(`explorer.exe`, a Windows-installed `code`) stop being reachable from inside WSL.

**Read the receipts.** The failed run wrote a full report:

```bash
cat ~/.local/state/play-bootstrap/runs/20260901T161239323046Z.md
python3 -m json.tool ~/.local/state/play-bootstrap/runs/20260901T161239323046Z.json | less
cat ~/.rote/log/install.log
```

## Already settled — do not re-debug

- **OAuth works.** The failed run printed `✓ Signed in with Google`.
- **Prerequisites pass.** Ubuntu 26.04, Python 3.14.4, curl 8.18.0, uv 0.12.8 at `~/.local/bin/uv`.
- **Network is fine.** rote v0.77.0 linux-x86_64 downloaded and unpacked before the failure.
- **Nothing is damaged.** Do not run `play-bootstrap restore` — there is no prior state to restore.
- **Work from `~`, not `/mnt/c`** — the Windows mount has slow I/O and awkward permissions.

## Do not

- Run the installer under `sudo`. It installs into your home directory by design.
- Install Node merely to satisfy the Windows codex shim — that makes a Windows binary execute
  against Linux paths, which may appear to work and then fail more strangely.
- Select Codex in the harness picker until `which codex` shows a Linux path.

## Reference

- Installer channel pins `modiqo/play@v0.4.82`.
- Exit code `77` from rote means login is required, not a network failure.
- The installer is convergent (`FRESH` / `VERIFY` / `UPDATE` / `REPAIR`), so re-running it is safe
  and is the documented update path.
- Prefixes: `/play` in Claude Code and Cursor, `$play` in Codex, `/skill:play` in Kimi.
- Windows is not supported natively; WSL2, Linux and macOS are.
