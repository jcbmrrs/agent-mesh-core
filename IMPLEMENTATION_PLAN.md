# AgentMesh Core — Implementation Plan (TDD-first)

## Context

`agent-mesh-core` currently contains only design docs (`BACKGROUND.md`, `MULTI-AGENT-GUIDE.md`, `PROMPT.md`) describing a multi-agent coordination mesh: an SMB-shared directory (via Tailscale, no port forwarding) where Claude Code / Codex / Ollama instances on different machines exchange JSON messages and state without ever writing concurrently to one shared mutable file. The core risk the design guards against is SMB's inconsistent cross-platform locking (AFP vs POSIX vs Windows oplocks) — solved via per-agent inboxes, atomic temp-file-then-rename writes, and directory-creation-based (`mkdir`/`rmdir`) locking.

Nothing has been implemented yet. This plan builds the full PROMPT.md scope as an installable, uv-managed Python package with a strict TDD test suite, so the coordination logic is proven correct before it ever touches a real SMB mount.

**Confirmed scope decisions** (already agreed, not open for re-litigation):
- Full PROMPT.md scope: coordinator + inbox scanning + `local_rules.json` template generator + macOS SMB provisioning script.
- uv-managed package: `pyproject.toml`, `src/agent_mesh_core/` layout, pytest + ruff.
- Mesh root is always a configurable path; tests use `tmp_path`, never a real `/Users/Shared/AgentMesh`.
- Per `PROJECT-SETUP.md`: this repo is the source-of-truth zone (code + templates + `deploy.sh`); `/Users/Shared/AgentMesh` is the live, git-ignored data zone, populated only via `deploy.sh` → the packaged bootstrap entrypoint. See `AGENTS.md`'s "Repo vs. live share split" section.

**Resolved after adversarial review (`PLAN_FEEDBACK.md`):**
- **No executable code is ever deployed into `/Users/Shared/AgentMesh`, full stop.** The live share is data-only (`agents/*/state.json`, `agents/*/inbox/*`, `locks/`, `config/local_rules.json`). Every machine that participates runs the package from its own git checkout (`git pull` + `uv sync`); `deploy.sh` only ever writes data. `PROMPT.md`'s literal `/Users/Shared/AgentMesh/agent_core.py` path is permanently superseded, not "later" satisfied — there is no compat shim.
- **Stale-lock breaking is dropped from v1.** It was hardening added during design, not part of the original spec, and mtime-based staleness is unsafe under SMB clock skew / sleep-wake / slow IO — it can break a valid long-running lock, and `release_lock` would need an ownership token to be safe even then. Locking in v1 is exactly what the original boilerplate specified: `mkdir`/`rmdir` + timeout/retry, nothing more. A tokenized-lease protocol is real future work, not a silent v1 feature.
- **Filesystem watchers are explicitly deferred**, not implied production behavior. v1 ships `scan_and_clear_inbox` only (poll-driven); a `watchdog`-based watcher is a v2 concern once there's an actual need for lower-latency delivery.
- **`config/file_trees.json`** (named in `MULTI-AGENT-GUIDE.md`'s architecture diagram) is **not built in v1** — it was never in this plan's module list. Constraint for whenever it is built: it must follow the same read-only/single-writer pattern as `local_rules.json` (aggregated by one designated process or the human operator), never written concurrently by multiple agents, or it violates the no-shared-mutable-file invariant.
- **Agent/lock names are validated** (`names.py`) before they ever become path components, closing the path-traversal/collision gap the original boilerplate left open.
- **Inbox scanning claims messages atomically** (rename into `.processing/` before read) and **quarantines malformed messages** instead of leaving them for endless rediscovery.
- **Temp filenames for atomic writes are collision-resistant** (`tempfile.mkstemp`, not `.tmp_<name>_<pid>`), since PIDs collide across machines.
- **SMB provisioning stays a dry-run command generator in v1** — no change to scope, just confirming this explicitly: real macOS privilege/ACL/version behavior and rollback are manual follow-up work on the Mac mini itself, not something this plan's test suite can or should exercise.

**Resolved after second adversarial review (`PLAN_FEEDBACK-2.md`):**
- **Claimed-but-unfinished inbox messages get a manual recovery path, not automatic requeue.** Claiming into `.processing/` (above) created a new failure mode: a crash between claim and delete leaves a message invisible forever. Fix: claim writes a sidecar `<name>.claim.json` (claimant `agent_id` + claimed-at timestamp) alongside the moved message, and a separate `recover_processing(older_than_seconds, action)` function inspects `.processing/` and requeues-or-quarantines old claims — but **only when an operator explicitly calls it with an explicit age threshold**. It is never invoked automatically by `scan_and_clear_inbox`, deliberately, so we don't reintroduce the same mtime-based staleness hazard we just rejected for locks.
- **Historical docs now carry "superseded" banners.** `MULTI-AGENT-GUIDE.md`, `PROJECT-SETUP.md`, and `PROMPT.md` still contain their original unsafe boilerplate (PID temp names, unvalidated paths, read-then-delete, direct-to-share writes) for historical/rationale value, but each now opens with an explicit banner pointing to this file and `AGENTS.md` for the actual v1 design, so a future reader can't mistake the draft for the plan.
- **`deploy.sh`'s responsibility is now singular and explicit.** It runs *locally*, on one already-set-up machine (typically the Mac mini, which has the mesh root mounted/local and the package installed), and does exactly one thing: invoke `agent-mesh-bootstrap` to populate the live share's *data*. It never touches another machine and never distributes code. Getting the code onto any given machine (Mac mini, MBP, future Linux/Windows box) is a separate, manual, per-machine `git pull && uv sync`, entirely outside `deploy.sh`'s job — those are two different deployment models and the plan no longer conflates them.
- **`acquire_lock` returns a lock handle, not a bare bool.** `release_lock` takes that handle rather than a raw `lock_name` string. This is a process-local safety net against double-release or releasing a lock a caller never actually acquired — it deliberately does **not** attempt cross-process/cross-machine ownership verification (e.g. writing an owner-id into the lock dir), since that reintroduces the same kind of staleness/ownership complexity already rejected for stale-lock breaking.
- **Atomic write sequence is now explicit**: `mkstemp` in the target directory → write JSON → `flush()` → `os.fsync(fd)` → `close()` → `os.replace()` → best-effort temp cleanup on any exception. Durability (not just naming-collision-safety) is now a stated requirement, not implied.
- **Message ordering semantics are declared, not implied.** Inbox processing order is **best-effort filename order only — no cross-machine causal or wall-clock guarantee** (clocks skew/drift across machines). Tests assert exactly that weaker behavior; we are not adding per-sender sequence numbers in v1, since nothing in scope currently depends on strict cross-machine ordering (that's a v2 concern if/when a real use case needs it).
- **`bootstrap_mesh` is operator/admin tooling, not agent runtime API.** It's the one thing in this package allowed to write `local_rules.json`, and it's meant to be invoked deliberately by a human (via `deploy.sh`) against a specific mesh root — never called by a routine agent process at runtime. Documented explicitly so the distinction survives the console-script entry point existing at all.
- **Name validation now also rejects Windows-reserved device names** (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, case-insensitive) and **requires lowercase**, closing the case-collision gap on case-insensitive mounts (macOS default, Windows). `bootstrap_mesh` rejects duplicate agent IDs after lowercase normalization.
- **SMB provisioning scope language tightened, module not renamed.** The plan no longer calls `smb_provision.py` "the SMB provisioning script" as if it performs provisioning — it's consistently described as a command generator/validator that emits and unit-tests `sharing`/`dscl` argument lists but never applies system configuration. Renaming the module (e.g. to `smb_provision_plan.py`) was considered and rejected as unnecessary churn; the docstring/description change is enough.

## Repo layout

```
agent-mesh-core/
├── pyproject.toml
├── .gitignore
├── deploy.sh                        # thin, local-only: invoke `agent-mesh-bootstrap` against the mounted share
├── src/agent_mesh_core/
│   ├── __init__.py
│   ├── names.py             # validate_name(): strict portable regex + Windows-reserved-name/lowercase checks
│   ├── coordinator.py       # AgentMeshCoordinator: LockHandle-based locks, atomic_write_json (fsync'd), update_state, send_message
│   ├── inbox.py             # scan_and_clear_inbox + InboxScanResult (claim-then-process via rename) + recover_processing()
│   ├── rules_template.py    # local_rules.json generator/writer
│   ├── bootstrap.py         # bootstrap_mesh(): wires coordinator init + rules template + default agent dirs
│   ├── smb_provision.py     # sharing/dscl command builders + provision_share(runner=...)
│   └── templates/
│       └── local_rules.template.json    # master template PROJECT-SETUP.md refers to as src/templates/
├── scripts/
│   └── provision_smb_share.py   # thin CLI wrapper, subprocess.run as the real runner
└── tests/
    ├── conftest.py
    ├── test_names.py
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

`PROMPT.md` literally names a deployed `/Users/Shared/AgentMesh/agent_core.py`. That path is **not built** — see "Resolved after adversarial review" above. Every machine runs `agent_mesh_core` from its own git checkout; the live share never contains code.

`PROJECT-SETUP.md`'s draft `deploy.sh` directly `cp`s a flat `agent_core.py` and does its own `[ -f ... ]` existence check before copying `local_rules.json`. Both parts are superseded: no code is copied anywhere (see above), and the "don't overwrite an existing config" rule is already a tested unit (`rules_template.write_local_rules_template`'s `force=False` default). `deploy.sh` runs locally on one already-set-up machine and calls the `agent-mesh-bootstrap` console script to populate the share's data — nothing more. It does not `cp` code, does not touch any other machine, and does not reimplement any logic itself. Getting the package onto a given machine (Mac mini, MBP, future Linux/Windows box) is a separate manual `git pull && uv sync`, run independently on that machine — not `deploy.sh`'s concern.

## Logic Gate triage

**Passes the gate (Iron Rule, strict test-first):**
- `validate_name` — accepts/rejects agent IDs, lock names, and target agent IDs against a strict portable pattern, Windows-reserved device names, and mixed-case collisions; every public method that takes a name-derived path argument calls it
- Lock acquire/release — timeout/retry loop, `FileExistsError` handling, `LockHandle`-based release (no stale-lock breaking in v1, no cross-process ownership verification)
- `atomic_write_json` — temp-file write (collision-resistant naming via `mkstemp`), explicit flush+fsync before `os.replace`, cleanup-on-exception, error wrapping
- `update_state` payload shape and `extra_metadata=None → {}` defaulting
- `send_message` payload shape, missing-inbox error, message-id uniqueness under identical timestamps
- Inbox claim-then-process — atomic claim (message + `.claim.json` sidecar) via rename into `.processing/`, delete-after-success, malformed JSON quarantined (not left in place), tolerating concurrent-claim races, documented best-effort-only ordering
- `recover_processing` — reports/requeues/quarantines claims older than an explicit, caller-supplied age threshold; never invoked automatically
- `local_rules.json` generation — default content, deep-merge of overrides, refuse-to-overwrite without `force`
- SMB command construction — argument lists, input validation, orchestration over an injected runner (dry-run generator; no real provisioning)
- `bootstrap_mesh` orchestration — which agent dirs get created (with duplicate-after-normalization rejection), call order (coordinator init before rules template), and that it surfaces (not swallows) a refuse-to-overwrite error from the rules template step

**Does not pass the gate (write directly, minimal/no unit tests):**
- `mkdir(parents=True, exist_ok=True)` calls in `__init__` (one smoke test)
- Actual `os.mkdir`/`os.rmdir` syscalls
- Actual `subprocess` invocation of `sharing`/`dscl` (unsafe to exercise in CI)
- `scripts/provision_smb_share.py` (thin delegation)
- `deploy.sh` itself (shell orchestration only — invoking the already-tested `agent-mesh-bootstrap` entrypoint locally, nothing more)

## Test infrastructure

- `tests/conftest.py`: `mesh_root(tmp_path)` fixture; `coordinator_factory(mesh_root)` returning a callable `(agent_id) -> AgentMeshCoordinator` so tests can instantiate two "agents" against one root (lock contention, `send_message`).
- **Clock injection**: give the coordinator an optional `clock` dependency (default: real `time`), with a `FakeClock` test double (`.monotonic()`, `.sleep()` that advances a counter instead of blocking) — avoids real `time.sleep` in timeout tests.
- **Atomic-write failure simulation**: monkeypatch the `os.replace` reference inside `coordinator.py` to raise mid-call; assert temp file is cleaned up and `IOError` raised. A separate test asserts the `mkstemp` file descriptor is closed before `os.replace` is attempted (no fd leak) regardless of success or failure.
- **Lock concurrency strategy** (the crux invariant):
  1. Deterministic race — pre-create the lock dir directly to force the exact `FileExistsError` path.
  2. Two-coordinator scenario — `agent_a` acquires, `agent_b` (short timeout + `FakeClock`) fails, `agent_a` releases, `agent_b` retries and succeeds.
  3. One real-concurrency test with `ThreadPoolExecutor` (N threads, no fake clock, same lock name) asserting exactly one thread wins — the one test exercising actual OS-level `mkdir` atomicity.

## TDD cycle sequence

### `names.py`
1. `test_names.py` — accepts typical IDs (`agent_mac_mini`, `agent-mbp-2`); rejects empty string, path separators (`/`, `\`), `..`, absolute paths, leading dot/dash, length over 64, non-ASCII/whitespace, uppercase characters (lowercase-only policy, to avoid case-collisions on case-insensitive mounts), and Windows-reserved device names (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`, case-insensitive); `validate_name` raises `ValueError` with the offending value in the message (not silently truncates/sanitizes/lowercases).

### `coordinator.py`
2. `test_coordinator_init.py` — init creates `agents/<id>/inbox/` and `locks/`; rejects an invalid `agent_id` via `validate_name` before touching the filesystem.
3. `test_coordinator_locks.py` — `acquire_lock` returns a `LockHandle` (truthy, carries `lock_name`) on success and `None` on timeout; `release_lock(handle)` removes the lock dir; releasing an already-released handle a second time is a no-op (not an error); timeout returns `None` with no real sleep; retry-then-succeed via mocked `FileExistsError` once; two-coordinator contention; thread-pool exactly-one-winner race (exactly one thread gets a non-`None` handle); `lock_name` validated via `validate_name` before any `mkdir` attempt. (No stale-lock breaking, no cross-process ownership verification in v1 — see "Resolved after adversarial review" / "second adversarial review".)
4. `test_coordinator_atomic_write.py` — writes target content; creates missing parent dirs; temp file uses a collision-resistant name (`tempfile.mkstemp`, not PID-based) so two concurrent writers to the same target never share a temp path; full write sequence is `mkstemp` → write → `flush()` → `os.fsync(fd)` → `close()` → `os.replace()` (test spies on `os.fsync` to confirm it's called before replace); descriptor is closed even when a later step fails; cleans up temp file and raises `IOError` on `os.replace` failure; leaves existing target untouched if the temp-file write itself fails.
5. `test_coordinator_state.py` — payload shape (`agent_id`, `timestamp`, `status`, `active_tasks`, `metadata`); `None` metadata defaults to `{}`; provided metadata passed through; delegates to `atomic_write_json` (isolated via spy).
6. `test_coordinator_send_message.py` — raises `FileNotFoundError` for missing target inbox; `target_agent_id` validated via `validate_name`; payload shape (`sender`, `type`, `body`); unique message IDs even when the clock returns identical timestamps twice (drives a monotonic counter or `uuid4` suffix).

### `inbox.py`
7. `test_inbox_scan.py` — empty inbox; claims a message by renaming it (plus writing a `<name>.claim.json` sidecar recording `claimant_agent_id`/`claimed_at`) into `agents/<id>/inbox/.processing/` before reading it, so a second concurrent scan of the same inbox cannot also claim it (two scan calls racing on one message: exactly one gets it); then reads/deletes the claimed message + sidecar on success; sorted-by-filename processing order (not mtime) — asserted only as "best-effort filename order, no cross-machine causal guarantee" per the declared ordering semantics; ignores stray `.tmp_*`/hidden files and anything already in `.processing/`; malformed JSON is quarantined — renamed into `inbox/.invalid/` rather than left in place, reported in `InboxScanResult.skipped`, so a re-scan never rediscovers it; tolerates `Path.unlink`/rename raising `FileNotFoundError` from a concurrent scan.
8. `test_inbox_recovery.py` — `recover_processing(mesh_root, agent_id, older_than_seconds, action)` is a no-op when called with no stale claims; reports (dry-run / `action=None`) a claim whose sidecar `claimed_at` is older than `older_than_seconds` without touching it; `action="requeue"` moves an old claim's message back to the inbox root (available for reprocessing); `action="quarantine"` moves it to `.invalid/` instead; a claim younger than the threshold is left untouched under any action; never called by `scan_and_clear_inbox` itself — this is exclusively an explicit, operator-invoked utility.

### `rules_template.py`
9. `test_rules_template.py` — default output has required top-level keys (`schema_version`, `network_context`, `model_overrides`, `file_tree_exclusions`); standard exclusion patterns present (`.git`, `__pycache__`, `.venv`, `node_modules`); deep-merge of overrides preserves defaults; override values take precedence; `write_local_rules_template` refuses to overwrite without `force=True`, overwrites when `force=True`; delegates to `atomic_write_json` (spy-isolated).

### `smb_provision.py`
10. `test_smb_provision.py` — expected `sharing`/`dscl` CLI arg lists for add-share, enable-SMB, grant-access; `ValueError` on empty share name or path outside an allowed root; `provision_share(runner=...)` calls the injected runner once per command in the correct order; stops on first nonzero return code without invoking later commands, error includes captured stderr. This module is a **dry-run command generator/validator, not a provisioning tool** — real macOS privilege/ACL/version behavior is not exercised by tests and is explicitly out of scope.

### `bootstrap.py`
11. `test_bootstrap.py` — `bootstrap_mesh(mesh_root, agent_ids, rules_overrides=None, force_rules=False)` creates a coordinator (and thus `agents/<id>/inbox/`, `locks/`) for every id in `agent_ids`, validating each via `validate_name`; rejects `agent_ids` that collide after lowercase normalization (e.g. `agent_mbp` + `Agent_MBP`) before creating anything; writes `config/local_rules.json` via `rules_template` exactly once; raises (does not swallow) `FileExistsError` from the rules-template step when `local_rules.json` already exists and `force_rules=False`; passing `force_rules=True` overwrites it; call order is coordinator/dir creation before the rules-template write.

### Integration (smoke-level, not micro-cycled)
12. `test_bootstrap_integration.py` — one end-to-end run of `bootstrap_mesh` against `tmp_path` asserting the full real directory tree + a valid `local_rules.json`, for the three default agent ids (`agent_mac_mini`, `agent_mbp`, `agent_ollama_local`). No code-deployment shim exists or is tested — the live share is data-only.

## Tooling setup

1. Author `pyproject.toml` by hand (repo already has content, don't `uv init` over it): `hatchling` build backend, `requires-python = ">=3.11"`, src-layout pointing at `src/agent_mesh_core`.
2. Dev deps via `uv add --dev pytest ruff` once the file exists.
3. `[project.scripts]` entries: `agent-mesh-provision-smb = "agent_mesh_core.smb_provision:main"` and `agent-mesh-bootstrap = "agent_mesh_core.bootstrap:main"` (the latter is what `deploy.sh` invokes).
4. `[tool.pytest.ini_options] testpaths = ["tests"]`; `[tool.ruff]` with `select = ["E", "F", "I"]`.
5. `.gitignore` (already applied — see repo's `.gitignore`): runtime paths from `PROJECT-SETUP.md` (`.tmp_*`, `*.lock`, `agents/`, `locks/`, `config/*.json` except `*.template.json`), plus standard Python/OS ignores, per `BACKGROUND.md`'s instruction to never track the live execution directory.
6. `uv sync`, then `uv run pytest` / `uv run ruff check .` as the ongoing dev loop.
7. `deploy.sh` — a thin, single-purpose, *local* wrapper (not a TDD cycle): run on a machine that already has this repo cloned/updated and `uv sync`'d, with `/Users/Shared/AgentMesh` mounted. It runs exactly one command: `uv run agent-mesh-bootstrap --mesh-root /Users/Shared/AgentMesh --agent-ids agent_mac_mini,agent_mbp,agent_ollama_local`. It does not `git pull`, does not touch any other machine, and does not distribute code — getting the package onto each participating machine is a separate, manual, per-machine step. All the logic `deploy.sh` depends on (directory creation, refuse-to-overwrite config, duplicate-ID rejection) is already covered by `test_bootstrap.py` and lower-level unit tests.

## Verification

- `uv run pytest -v` — full suite green, including the thread-pool lock race (run a few times to confirm it's not flaky).
- `uv run ruff check .` — clean.
- Manual smoke: instantiate `AgentMeshCoordinator` twice against the same `tmp_path`-like real directory outside pytest (e.g. a scratch dir), exercise `send_message` + inbox scan across the pair, confirm no leftover `.tmp_*` files.
- Manual smoke: run `deploy.sh` against a scratch directory (not the real `/Users/Shared/AgentMesh`) to confirm it produces the same tree `test_bootstrap_integration.py` asserts, then re-run it to confirm `local_rules.json` is left untouched (no `force_rules`).
- Manual smoke: simulate a crash mid-claim (move a message into `.processing/` with a sidecar by hand), confirm `scan_and_clear_inbox` leaves it alone, then confirm `recover_processing` reports/requeues/quarantines it correctly depending on the age threshold and `action` passed.
- SMB provisioning script is **not** run for real during this task — command construction is verified via the injected-runner unit tests only; actual `sharing`/`dscl` execution is a manual follow-up on the Mac mini itself, outside this plan's scope.
