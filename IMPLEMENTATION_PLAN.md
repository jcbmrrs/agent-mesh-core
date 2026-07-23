# AgentMesh Core — Implementation Plan (TDD-first)

## Context

`agent-mesh-core` currently contains only design docs (`BACKGROUND.md`, `MULTI-AGENT-GUIDE.md`, `PROMPT.md`) describing a multi-agent coordination mesh: an SMB-shared directory (via Tailscale, no port forwarding) where Claude Code / Codex / Ollama instances on different machines exchange JSON messages and state without ever writing concurrently to one shared mutable file. The core risk the design guards against is SMB's inconsistent cross-platform locking (AFP vs POSIX vs Windows oplocks) — solved via per-agent inboxes, atomic temp-file-then-rename writes, and directory-creation-based (`mkdir`/`rmdir`) locking.

Nothing has been implemented yet. This plan builds the full PROMPT.md scope as an installable, uv-managed Python package with a strict TDD test suite, so the coordination logic is proven correct before it ever touches a real SMB mount.

**Confirmed scope decisions** (already agreed, not open for re-litigation):
- Full PROMPT.md scope: coordinator + inbox scanning + `local_rules.json` template generator + macOS SMB provisioning script.
- uv-managed package: `pyproject.toml`, `src/agent_mesh_core/` layout, pytest + ruff.
- Mesh root is always a configurable path; tests use `tmp_path`, never a real `/Users/Shared/AgentMesh`.
- Per `PROJECT-SETUP.md`: this repo is the source-of-truth zone (code + templates + `deploy.sh`); `/Users/Shared/AgentMesh` is the live, git-ignored data zone, populated only via `deploy.sh` → the packaged bootstrap entrypoint. See `AGENTS.md`'s "Repo vs. live share split" section.

## Repo layout

```
agent-mesh-core/
├── pyproject.toml
├── .gitignore
├── deploy.sh                        # thin: sync repo + invoke `agent-mesh-bootstrap` on the target
├── src/agent_mesh_core/
│   ├── __init__.py
│   ├── coordinator.py       # AgentMeshCoordinator: locks, atomic_write_json, update_state, send_message
│   ├── inbox.py             # scan_and_clear_inbox + InboxScanResult
│   ├── rules_template.py    # local_rules.json generator/writer
│   ├── bootstrap.py         # bootstrap_mesh(): wires coordinator init + rules template + default agent dirs
│   ├── smb_provision.py     # sharing/dscl command builders + provision_share(runner=...)
│   └── templates/
│       └── local_rules.template.json    # master template PROJECT-SETUP.md refers to as src/templates/
├── scripts/
│   └── provision_smb_share.py   # thin CLI wrapper, subprocess.run as the real runner
└── tests/
    ├── conftest.py
    ├── test_coordinator_init.py
    ├── test_coordinator_locks.py
    ├── test_coordinator_atomic_write.py
    ├── test_coordinator_state.py
    ├── test_coordinator_send_message.py
    ├── test_inbox_scan.py
    ├── test_rules_template.py
    ├── test_smb_provision.py
    ├── test_bootstrap.py
    └── test_bootstrap_integration.py
```

`PROMPT.md` literally names a deployed `/Users/Shared/AgentMesh/agent_core.py`. Real logic lives in `src/agent_mesh_core/`; a tiny re-export shim (`from agent_mesh_core.coordinator import AgentMeshCoordinator`) can later satisfy that literal path. The shim is plumbing — one smoke test, not a TDD cycle.

`PROJECT-SETUP.md`'s draft `deploy.sh` directly `cp`s a flat `agent_core.py` and does its own `[ -f ... ]` existence check before copying `local_rules.json`. That's adapted here: since the real source is a `src/agent_mesh_core/` package (not a flat script), and the "don't overwrite an existing config" rule is already a tested unit (`rules_template.write_local_rules_template`'s `force=False` default), `deploy.sh` stays a thin shell wrapper that ensures the package is present on the target and calls the `agent-mesh-bootstrap` console script — it does not reimplement any of that logic itself.

## Logic Gate triage

**Passes the gate (Iron Rule, strict test-first):**
- Lock acquire/release — timeout/retry loop, stale-lock detection/breaking, `FileExistsError` handling
- `atomic_write_json` — temp-file write, move, cleanup-on-exception, error wrapping
- `update_state` payload shape and `extra_metadata=None → {}` defaulting
- `send_message` payload shape, missing-inbox error, message-id uniqueness under identical timestamps
- Inbox scan-and-delete — ordering, delete-after-success, malformed JSON handling, ignoring temp/hidden files, tolerating concurrent-delete races
- `local_rules.json` generation — default content, deep-merge of overrides, refuse-to-overwrite without `force`
- SMB command construction — argument lists, input validation, orchestration over an injected runner
- `bootstrap_mesh` orchestration — which agent dirs get created, call order (coordinator init before rules template), and that it surfaces (not swallows) a refuse-to-overwrite error from the rules template step

**Does not pass the gate (write directly, minimal/no unit tests):**
- `mkdir(parents=True, exist_ok=True)` calls in `__init__` (one smoke test)
- Actual `os.mkdir`/`os.rmdir` syscalls
- Actual `subprocess` invocation of `sharing`/`dscl` (unsafe to exercise in CI)
- `scripts/provision_smb_share.py` and the `agent_core.py` compat shim (thin delegation)
- `deploy.sh` itself (shell orchestration only — repo sync + invoking the already-tested `agent-mesh-bootstrap` entrypoint)

## Test infrastructure

- `tests/conftest.py`: `mesh_root(tmp_path)` fixture; `coordinator_factory(mesh_root)` returning a callable `(agent_id) -> AgentMeshCoordinator` so tests can instantiate two "agents" against one root (lock contention, `send_message`).
- **Clock injection**: give the coordinator an optional `clock` dependency (default: real `time`), with a `FakeClock` test double (`.monotonic()`, `.sleep()` that advances a counter instead of blocking) — avoids real `time.sleep` in timeout tests.
- **Atomic-write failure simulation**: monkeypatch the `shutil.move` reference inside `coordinator.py` to raise mid-call; assert temp file is cleaned up and `IOError` raised.
- **Lock concurrency strategy** (the crux invariant):
  1. Deterministic race — pre-create the lock dir directly to force the exact `FileExistsError` path.
  2. Two-coordinator scenario — `agent_a` acquires, `agent_b` (short timeout + `FakeClock`) fails, `agent_a` releases, `agent_b` retries and succeeds.
  3. One real-concurrency test with `ThreadPoolExecutor` (N threads, no fake clock, same lock name) asserting exactly one thread wins — the one test exercising actual OS-level `mkdir` atomicity.

## TDD cycle sequence

### `coordinator.py`
1. `test_coordinator_init.py` — init creates `agents/<id>/inbox/` and `locks/`.
2. `test_coordinator_locks.py` — acquire success; release removes dir; release-on-missing is a no-op; timeout returns `False` with no real sleep; retry-then-succeed via mocked `FileExistsError` once; stale-lock breaking past a threshold (`os.utime` into the past); fresh lock not broken; two-coordinator contention; thread-pool exactly-one-winner race.
3. `test_coordinator_atomic_write.py` — writes target content; creates missing parent dirs; cleans up temp file and raises `IOError` on `shutil.move` failure; leaves existing target untouched if the temp-file write itself fails.
4. `test_coordinator_state.py` — payload shape (`agent_id`, `timestamp`, `status`, `active_tasks`, `metadata`); `None` metadata defaults to `{}`; provided metadata passed through; delegates to `atomic_write_json` (isolated via spy).
5. `test_coordinator_send_message.py` — raises `FileNotFoundError` for missing target inbox; payload shape (`sender`, `type`, `body`); unique message IDs even when the clock returns identical timestamps twice (drives a monotonic counter or `uuid4` suffix).

### `inbox.py`
6. `test_inbox_scan.py` — empty inbox; read-and-delete single message; sorted-by-filename processing order (not mtime); ignores stray `.tmp_*`/hidden files; malformed JSON is skipped and retained (reported in `InboxScanResult.skipped`); tolerates `Path.unlink` raising `FileNotFoundError` from a concurrent scan.

### `rules_template.py`
7. `test_rules_template.py` — default output has required top-level keys (`schema_version`, `network_context`, `model_overrides`, `file_tree_exclusions`); standard exclusion patterns present (`.git`, `__pycache__`, `.venv`, `node_modules`); deep-merge of overrides preserves defaults; override values take precedence; `write_local_rules_template` refuses to overwrite without `force=True`, overwrites when `force=True`; delegates to `atomic_write_json` (spy-isolated).

### `smb_provision.py`
8. `test_smb_provision.py` — expected `sharing`/`dscl` CLI arg lists for add-share, enable-SMB, grant-access; `ValueError` on empty share name or path outside an allowed root; `provision_share(runner=...)` calls the injected runner once per command in the correct order; stops on first nonzero return code without invoking later commands, error includes captured stderr.

### `bootstrap.py`
9. `test_bootstrap.py` — `bootstrap_mesh(mesh_root, agent_ids, rules_overrides=None, force_rules=False)` creates a coordinator (and thus `agents/<id>/inbox/`, `locks/`) for every id in `agent_ids`; writes `config/local_rules.json` via `rules_template` exactly once; raises (does not swallow) `FileExistsError` from the rules-template step when `local_rules.json` already exists and `force_rules=False`; passing `force_rules=True` overwrites it; call order is coordinator/dir creation before the rules-template write.

### Integration (smoke-level, not micro-cycled)
10. `test_bootstrap_integration.py` — one end-to-end run of `bootstrap_mesh` against `tmp_path` asserting the full real directory tree + a valid `local_rules.json`, for the three default agent ids (`agent_mac_mini`, `agent_mbp`, `agent_ollama_local`); `agent_core.py` shim re-exports the coordinator class (smoke-only).

## Tooling setup

1. Author `pyproject.toml` by hand (repo already has content, don't `uv init` over it): `hatchling` build backend, `requires-python = ">=3.11"`, src-layout pointing at `src/agent_mesh_core`.
2. Dev deps via `uv add --dev pytest ruff` once the file exists.
3. `[project.scripts]` entries: `agent-mesh-provision-smb = "agent_mesh_core.smb_provision:main"` and `agent-mesh-bootstrap = "agent_mesh_core.bootstrap:main"` (the latter is what `deploy.sh` invokes).
4. `[tool.pytest.ini_options] testpaths = ["tests"]`; `[tool.ruff]` with `select = ["E", "F", "I"]`.
5. `.gitignore` (already applied — see repo's `.gitignore`): runtime paths from `PROJECT-SETUP.md` (`.tmp_*`, `*.lock`, `agents/`, `locks/`, `config/*.json` except `*.template.json`), plus standard Python/OS ignores, per `BACKGROUND.md`'s instruction to never track the live execution directory.
6. `uv sync`, then `uv run pytest` / `uv run ruff check .` as the ongoing dev loop.
7. `deploy.sh` — a thin wrapper (not a TDD cycle) that: ensures the repo/package is present on the target machine, then runs `uv run agent-mesh-bootstrap --mesh-root /Users/Shared/AgentMesh --agent-ids agent_mac_mini,agent_mbp,agent_ollama_local`. All the actual logic it depends on (directory creation, refuse-to-overwrite config) is already covered by `test_bootstrap.py` and lower-level unit tests.

## Verification

- `uv run pytest -v` — full suite green, including the thread-pool lock race (run a few times to confirm it's not flaky).
- `uv run ruff check .` — clean.
- Manual smoke: instantiate `AgentMeshCoordinator` twice against the same `tmp_path`-like real directory outside pytest (e.g. a scratch dir), exercise `send_message` + inbox scan across the pair, confirm no leftover `.tmp_*` files.
- Manual smoke: run `deploy.sh` against a scratch directory (not the real `/Users/Shared/AgentMesh`) to confirm it produces the same tree `test_bootstrap_integration.py` asserts, then re-run it to confirm `local_rules.json` is left untouched (no `force_rules`).
- SMB provisioning script is **not** run for real during this task — command construction is verified via the injected-runner unit tests only; actual `sharing`/`dscl` execution is a manual follow-up on the Mac mini itself, outside this plan's scope.
