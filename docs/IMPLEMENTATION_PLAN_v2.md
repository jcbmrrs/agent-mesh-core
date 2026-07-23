# AgentMesh Core — Implementation Plan v2 (TDD-first)

## Context

`agent-mesh-core` is a multi-agent coordination mesh: a shared directory
where Claude Code, Codex, and local Ollama instances on different machines
exchange JSON messages and state without ever writing concurrently to one
shared mutable file. **The coordinator runs as an MCP server process on
the Mac mini.** Claude Code and Codex on other machines (MBP M3 Pro, and
eventually Linux/Windows boxes) register that server, reached over the Mac
mini's Tailscale IP/MagicDNS name, exactly as they'd register any other
MCP server — no filesystem mount, no client-side access to the mesh root
at all. Ollama-backed tooling, which doesn't speak MCP, reaches the same
underlying functions through a thin HTTP wrapper. **No machine other than
the Mac mini ever touches `/Users/Shared/AgentMesh` directly** — the
coordinator only ever runs against local POSIX disk.

Nothing has been implemented yet. This plan builds the coordinator, inbox
scanning, and `local_rules.json` template generator as an installable,
uv-managed Python package with a strict TDD test suite, so the
coordination logic is proven correct before it's wrapped by the MCP
server.

*Design history: this plan was originally written for an SMB-mount-by-
every-client transport and hardened across four rounds of adversarial
review before the transport was replaced with the MCP-server design above.
None of the reviewed correctness logic (lock ownership tokens, atomic
claim-then-process inbox handling, path/symlink confinement, name
validation) was actually SMB-specific — it carries forward unchanged here,
now defending local-filesystem correctness rather than a network mount.
See `docs/archive/IMPLEMENTATION_PLAN_v1.md` and
`docs/archive/PLAN_FEEDBACK.md` through `PLAN_FEEDBACK-4.md` for the
incremental derivation, and `docs/PROBLEM_STATEMENT.md` /
`docs/SOLUTION_RECOMMENDATION.md` for why the transport changed.*

## Confirmed scope

- **In scope, fully cycled below:** `names.py`, `coordinator.py`
  (locks, atomic writes, state, messaging), `inbox.py` (scan + recovery),
  `rules_template.py`, `bootstrap.py`.
- **Named in the repo layout but not yet cycled:** `mcp_server.py`,
  wrapping the runtime-facing coordinator methods as MCP tools. Its
  tool-registration/dispatch shape needs its own design pass — the
  coordinator logic needs to exist and pass its own tests before there's
  anything to wrap in a tool, and designing that shape now would be
  designing for a module that doesn't exist yet. Same treatment for the
  Ollama HTTP wrapper (a thin set of routes over the same functions
  `mcp_server.py` calls, sharing a dispatch layer rather than duplicating
  logic).
- **Not in scope, dropped entirely (not deferred):** any SMB-share
  provisioning tooling (`sharing`/`dscl` command generation). No client
  ever mounts the mesh root, so there is nothing to provision.
- uv-managed package: `pyproject.toml`, `src/agent_mesh_core/` layout,
  pytest + ruff.
- Mesh root is always a configurable path; tests use `tmp_path`, never a
  real `/Users/Shared/AgentMesh`.
- This repo is the source-of-truth zone (code + templates + `deploy.sh`);
  `/Users/Shared/AgentMesh` is the live, git-ignored data zone on the Mac
  mini, populated only via `deploy.sh` → the packaged bootstrap entrypoint.
  See `AGENTS.md`'s "Repo vs. live share split" section.

## Design invariants

- **No single shared mutable file.** Per-agent inboxes, not a shared
  queue: each agent only ever writes into *another* agent's `inbox/`.
- **Atomic writes only.** `mkstemp` (collision-resistant naming) → write
  → `flush()` → `os.fsync(fd)` → `close()` → `os.replace()` → best-effort
  parent-directory fsync (swallows `OSError` if unsupported). Descriptor
  is closed even when a later step fails; a non-serializable payload (e.g.
  a raw `set()`) leaves no target or temp file.
- **`atomic_write_json` is confined to the mesh root.** Rejects (raises)
  any `target_file_path` outside `self.mesh_root`, and rejects any
  symlink anywhere in the path between the mesh root and the target — even
  one that would still resolve back inside the mesh root. Symlinks are
  unsupported everywhere in mesh-managed paths, full stop; `send_message`
  fails closed (raises) on a symlinked target inbox rather than following it.
- **Locking is directory-creation based**, not file-based: `os.mkdir()`
  on a path under `locks/` — lock acquisition = successful `mkdir`,
  release = `rmdir`. Never a plain lock *file*. On successful `mkdir`,
  `acquire_lock` writes a random token into `<lock_dir>/owner.token` and
  returns it inside a `LockHandle`; if that write itself raises,
  `acquire_lock` rolls back its own `mkdir` and treats the attempt as
  failed. `release_lock(handle)`: missing token file or mismatched token
  → no-op, lock left alone; matching token → remove the token then
  `rmdir` the lock dir; if `rmdir` then fails because unexpected extra
  files are present, that **raises** rather than deleting the unknown
  contents. Releasing an already-released handle a second time is a
  deliberate no-op (safe `try/finally` cleanup). **No stale-lock breaking
  in v1** — a true hard crash between `mkdir` and a successful token write
  is an accepted limitation requiring manual operator cleanup, not
  automatic detection/repair.
- **Agent IDs, lock names, and target agent IDs are validated** before
  they become path components: a strict portable pattern (no
  separators/`..`/absolute paths), **lowercase-only** (avoids collisions
  on case-insensitive filesystems), and rejection of Windows-reserved
  device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`).
- **Inbox messages are claimed before processing**, not read-then-deleted.
  A single atomic `mkdir(.processing/<claim_id>/)` (retried with a new ID
  on a rare claim-ID collision, bounded retry count) is followed by
  renaming the message into it — **the rename, not the `mkdir`, enforces
  exclusivity**, since only one renamer can win against the shared source
  path — then a `.claim.json` sidecar is written. Malformed messages are
  quarantined into `inbox/.invalid/`, never left in place for endless
  rediscovery; other ignored files (stray `.tmp_*`/hidden) are reported in
  `InboxScanResult.ignored`, not silently dropped. A crashed/killed
  claimant leaves its claim in one of four identifiable states — empty
  dir, message-without-sidecar, message-with-malformed-sidecar, or a
  complete claim — recoverable only via an explicit, operator-invoked
  `recover_processing(older_than_seconds | claim_ids, action)` call, never
  automatically. An *empty* claim dir is **not** a special case removed
  unconditionally — it's also the normal transient state of a live
  scanner mid-claim, so it goes through the exact same age/selection
  rules as every other shape; recovery should be run while the target
  agent is stopped. The age threshold is a heuristic, not a correctness
  guarantee (cross-machine clock skew) — `claim_ids` is the clock-skew-proof
  override. `requeue`/`quarantine` fail closed (raise) on a destination
  filename collision rather than overwriting.
- **Message ordering is best-effort filename order only** — no
  cross-machine causal or wall-clock guarantee. No per-sender sequence
  numbers in v1, since nothing in scope needs strict ordering yet.
- **Filesystem watchers are a v2+ concern.** v1 ships polling-only
  (`scan_and_clear_inbox`); prefer watchers (e.g. `watchdog`) over
  tighter polling loops once there's an actual latency need.
- **`config/local_rules.json` is read-only for agents** — written only by
  the human operator (via `bootstrap_mesh`/`deploy.sh`), never by any
  agent process at runtime. The same single-writer rule applies to
  `file_trees.json` whenever it's eventually built (not in this plan's
  scope).

## Repo layout

```
agent-mesh-core/
├── pyproject.toml
├── .gitignore
├── deploy.sh                        # thin, local-only: invoke `agent-mesh-bootstrap` against the local mesh root
├── src/agent_mesh_core/
│   ├── __init__.py
│   ├── names.py             # validate_name(): strict portable regex + Windows-reserved-name/lowercase checks
│   ├── coordinator.py       # AgentMeshCoordinator: token-checked LockHandle locks, mesh-root-confined atomic_write_json (fsync'd), update_state, send_message
│   ├── inbox.py             # scan_and_clear_inbox + InboxScanResult (claim into .processing/<claim_id>/ dirs) + recover_processing()
│   ├── rules_template.py    # local_rules.json generator/writer
│   ├── bootstrap.py         # bootstrap_mesh(): wires coordinator init + rules template + default agent dirs
│   ├── mcp_server.py        # planned: wraps runtime-facing coordinator methods as MCP tools (design pass not yet done — see "Confirmed scope")
│   └── templates/
│       └── local_rules.template.json
└── tests/
    ├── conftest.py
    ├── test_names.py
    ├── test_coordinator_init.py
    ├── test_coordinator_locks.py
    ├── test_coordinator_atomic_write.py
    ├── test_coordinator_state.py
    ├── test_coordinator_send_message.py
    ├── test_inbox_scan.py
    ├── test_inbox_recovery.py
    ├── test_rules_template.py
    ├── test_bootstrap.py
    └── test_bootstrap_integration.py
```

Every machine either runs the MCP server (Mac mini only) or reaches it as
a registered MCP client (everyone else); the live share never contains
code and is never mounted by any machine but the Mac mini.

`deploy.sh` runs locally on the Mac mini and calls the
`agent-mesh-bootstrap` console script to populate the mesh root's data —
nothing more. It does not `cp` code and does not reimplement any logic
itself (the "don't overwrite an existing config" rule lives in
`rules_template.write_local_rules_template`'s `force=False` default, a
tested unit, not a bash guard). Other machines don't run `deploy.sh` at
all — they never touch the mesh root, only the MCP server (or HTTP
wrapper, for Ollama tooling) that fronts it.

## Logic Gate triage

**Passes the gate (Iron Rule, strict test-first):**
- `validate_name` — accepts/rejects agent IDs, lock names, and target
  agent IDs against a strict portable pattern, Windows-reserved device
  names, and mixed-case collisions; every public method that takes a
  name-derived path argument calls it
- Lock acquire/release — timeout/retry loop, `FileExistsError` handling,
  `LockHandle` with an ownership token checked on release, self-cleanup
  on token-write failure within the same call (no stale-lock breaking in
  v1, no time-based staleness anywhere)
- `atomic_write_json` — mesh-root path confinement (rejecting any symlink
  component, not just resolved escapes), temp-file write
  (collision-resistant naming via `mkstemp`), explicit flush+fsync
  (+best-effort parent-dir fsync) before `os.replace`, cleanup-on-exception
  including non-serializable-payload failures, error wrapping
- `update_state` payload shape and `extra_metadata=None → {}` defaulting
- `send_message` payload shape, missing-inbox error, target-is-not-a-directory
  error, message-id uniqueness under identical timestamps
- Inbox claim-then-process — atomic claim via `mkdir` (with bounded retry
  on claim-ID collision) + rename into `.processing/<claim_id>/` + sidecar
  write, delete-after-success, malformed JSON quarantined (not left in
  place), tolerating concurrent-claim races and all four orphan shapes,
  documented best-effort-only ordering, ignored files reported not dropped
- `recover_processing` — reports/requeues/quarantines claims (uniformly
  across all orphan shapes, including empty claim dirs) by age threshold
  (heuristic only) or by explicit `claim_ids` override, failing closed on
  a requeue/quarantine destination collision; never invoked automatically
- `local_rules.json` generation — default content, deep-merge of
  overrides, refuse-to-overwrite without `force`
- `bootstrap_mesh` orchestration — which agent dirs get created (with
  duplicate-after-normalization rejection), call order (coordinator init
  before rules template), and that it surfaces (not swallows) a
  refuse-to-overwrite error from the rules template step

**Does not pass the gate (write directly, minimal/no unit tests):**
- `mkdir(parents=True, exist_ok=True)` calls in `__init__` (one smoke test)
- Actual `os.mkdir`/`os.rmdir` syscalls
- `deploy.sh` itself (shell orchestration only — invoking the
  already-tested `agent-mesh-bootstrap` entrypoint locally, nothing more)

## Test infrastructure

- `tests/conftest.py`: `mesh_root(tmp_path)` fixture; `coordinator_factory(mesh_root)` returning a callable `(agent_id) -> AgentMeshCoordinator` so tests can instantiate two "agents" against one root (lock contention, `send_message`).
- **Clock injection**: give the coordinator an optional `clock` dependency (default: real `time`), with a `FakeClock` test double (`.monotonic()`, `.sleep()` that advances a counter instead of blocking) — avoids real `time.sleep` in timeout tests.
- **Atomic-write failure simulation**: monkeypatch the `os.replace` reference inside `coordinator.py` to raise mid-call; assert temp file is cleaned up and `IOError` raised. A separate test asserts the `mkstemp` file descriptor is closed before `os.replace` is attempted (no fd leak) regardless of success or failure. Directory-fsync-unsupported is simulated by monkeypatching that specific `os.fsync(dir_fd)` call to raise `OSError`, asserting it's swallowed and doesn't affect the already-completed write.
- **Lock ownership token**: `acquire_lock` tests can directly overwrite `<lock_dir>/owner.token` on disk between acquire and release to simulate "someone else's `mkdir` reacquired this lock name" without needing real multi-process coordination. A separate test monkeypatches the token-write step to raise, asserting `acquire_lock` removes the lock dir it just created and treats the attempt as failed. Another places an extra unexpected file inside a lock dir alongside a matching token, asserting `release_lock` raises rather than deleting the extra file or leaving the dir silently undeletable.
- **Symlink path-safety**: tests create a symlinked directory somewhere between `mesh_root` and a target path (including one that still resolves back inside `mesh_root`) and assert `atomic_write_json` rejects it — not relying on `Path.resolve()` alone.
- **Lock concurrency strategy** (the crux invariant):
  1. Deterministic race — pre-create the lock dir directly to force the exact `FileExistsError` path.
  2. Two-coordinator scenario — `agent_a` acquires, `agent_b` (short timeout + `FakeClock`) fails, `agent_a` releases, `agent_b` retries and succeeds.
  3. One real-concurrency test with `ThreadPoolExecutor` (N threads, no fake clock, same lock name) asserting exactly one thread wins — the one test exercising actual OS-level `mkdir` atomicity.

## TDD cycle sequence

### `names.py`
1. `test_names.py` — accepts typical IDs (`agent_mac_mini`, `agent-mbp-2`); rejects empty string, path separators (`/`, `\`), `..`, absolute paths, leading dot/dash, length over 64, non-ASCII/whitespace, uppercase characters (lowercase-only policy), and Windows-reserved device names (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`, case-insensitive); `validate_name` raises `ValueError` with the offending value in the message (not silently truncates/sanitizes/lowercases).

### `coordinator.py`
2. `test_coordinator_init.py` — init creates `agents/<id>/inbox/` and `locks/`; rejects an invalid `agent_id` via `validate_name` before touching the filesystem.
3. `test_coordinator_locks.py` — `acquire_lock` returns a `LockHandle` (truthy, carries `lock_name` + an opaque token) on success and `None` on timeout; on successful `mkdir`, an `owner.token` file is written inside the lock dir before the handle is returned; if that token write raises, `acquire_lock` removes the lock dir it just created and treats the attempt as failed (retries within the remaining timeout, or returns `None`) — test via a monkeypatched write that raises on the first attempt only; `release_lock(handle)` reads `owner.token`, and: missing file → no-op; mismatched token (simulate by manually swapping the on-disk token between acquire and release) → no-op, lock dir untouched; matching token → `os.remove(owner.token)` then `os.rmdir(lock_dir)`; a matching token that disappears between the read and the remove (simulated race) is treated as already-released, not an error; an unexpected extra file left in the lock dir alongside a valid matching token causes `rmdir` to fail on a non-empty directory, and this **raises** rather than deleting the extra file or silently leaving an undeletable lock dir; releasing an already-released handle a second time is a no-op; timeout returns `None` with no real sleep; retry-then-succeed via mocked `FileExistsError` once; two-coordinator contention; thread-pool exactly-one-winner race (exactly one thread gets a non-`None` handle); `lock_name` validated via `validate_name` before any `mkdir` attempt.
4. `test_coordinator_atomic_write.py` — writes target content; creates missing parent dirs; rejects a `target_file_path` that resolves outside `mesh_root` (absolute path elsewhere, `..` traversal) with `ValueError`, before any file is touched; rejects a path with any symlink component between `mesh_root` and the target — including a symlink that would still resolve back inside `mesh_root`; temp file uses a collision-resistant name (`tempfile.mkstemp`, not PID-based) so two concurrent writers to the same target never share a temp path; full write sequence is `mkstemp` → write → `flush()` → `os.fsync(fd)` → `close()` → `os.replace()` → best-effort parent-directory fsync that swallows `OSError` (test spies on both fsync calls, and separately confirms a parent-dir-fsync `OSError` doesn't propagate or affect the completed write); descriptor is closed even when a later step fails; cleans up temp file and raises `IOError` on `os.replace` failure; leaves existing target untouched if the temp-file write itself fails; passing a non-JSON-serializable payload (e.g. a `set()`) raises, leaves no temp file, and leaves any existing target untouched.
5. `test_coordinator_state.py` — payload shape (`agent_id`, `timestamp`, `status`, `active_tasks`, `metadata`); `None` metadata defaults to `{}`; provided metadata passed through; delegates to `atomic_write_json` (isolated via spy); a non-serializable value in `extra_metadata` propagates the same clean failure as `atomic_write_json`'s own test (no target/temp file left).
6. `test_coordinator_send_message.py` — raises `FileNotFoundError` for missing target inbox; raises `NotADirectoryError` when `agents/<target_id>/inbox` exists but is a file, not a directory; a symlink at that path is treated as unsupported and fails closed (raises, not resolved/followed); `target_agent_id` validated via `validate_name`; payload shape (`sender`, `type`, `body`); unique message IDs even when the clock returns identical timestamps twice (drives a monotonic counter or `uuid4` suffix); non-serializable `payload` fails cleanly (no message file left in the target inbox).

### `inbox.py`
7. `test_inbox_scan.py` — empty inbox; claims a message via `mkdir(.processing/<claim_id>/)` (not the exclusivity point; on `FileExistsError` from a claim-ID collision, retries with a new ID up to a bounded count — test this by forcing `FileExistsError` on the first generated ID) then `os.rename` of the original message into that dir as `<claim_id>/<original_filename>` (**this rename is the exclusivity point** — two concurrent scans racing the same source message: exactly one rename succeeds, the other gets `FileNotFoundError` and moves on, its now-empty claim dir removed), then writes `<claim_id>/<original_filename>.claim.json` (`claimant_agent_id`, `claimed_at`); reads/deletes the claimed message + sidecar + claim dir on success; sorted-by-filename processing order (not mtime) — asserted only as "best-effort filename order, no cross-machine causal guarantee"; ignores stray `.tmp_*`/hidden files and anything already in `.processing/`, and reports each ignored filename in `InboxScanResult.ignored` rather than dropping it silently; malformed JSON is quarantined — renamed into `inbox/.invalid/` rather than left in place, reported in `InboxScanResult.skipped`; tolerates `Path.unlink`/rename raising `FileNotFoundError` from a concurrent scan.
8. `test_inbox_recovery.py` — `recover_processing(mesh_root, agent_id, older_than_seconds=None, claim_ids=None, action=None)` is a no-op when called with no stale/matching claims; four orphan shapes handled explicitly, **all age-checked via the same selection rules** (no shape is ever unconditionally acted on): (a) an empty `.processing/<claim_id>/` (crash right after `mkdir`, before rename, **or** a live scanner's normal transient state between its own `mkdir` and rename) is age-checked via the claim directory's own mtime — critically, this means a fresh empty claim dir from an active scanner is left alone by default, only an old one is eligible; (b) a claim dir with the message file but no `.claim.json` sidecar is age-checked via the message file's mtime; (c) a claim dir whose sidecar exists but fails to parse (invalid JSON, missing `claimed_at`, or an invalid claimant) is treated like (b) — age-checked via message mtime, with the parse failure reported clearly in the result, not raised; (d) a normal claim (message + valid sidecar) is age-checked via the sidecar's `claimed_at`. Age-based selection (`older_than_seconds`) is documented and tested as a heuristic only; passing explicit `claim_ids` instead recovers exactly those claims regardless of age. `action=None` is dry-run/report-only; `action="requeue"` moves the message back to the inbox root **and raises if a file already exists at that destination** rather than overwriting it; `action="quarantine"` moves it to `.invalid/` with the same fail-closed-on-collision rule; a claim not selected (too young, or not in `claim_ids`) is left untouched under any action; never called by `scan_and_clear_inbox` itself — this is exclusively an explicit, operator-invoked utility, and the docs should say plainly that it's meant to be run while the target agent's own process is stopped, precisely because empty claim dirs are otherwise ambiguous with a live scanner's in-flight state.

### `rules_template.py`
9. `test_rules_template.py` — default output has required top-level keys (`schema_version`, `network_context`, `model_overrides`, `file_tree_exclusions`); standard exclusion patterns present (`.git`, `__pycache__`, `.venv`, `node_modules`); deep-merge of overrides preserves defaults; override values take precedence; `write_local_rules_template` refuses to overwrite without `force=True`, overwrites when `force=True`; delegates to `atomic_write_json` (spy-isolated).

### `bootstrap.py`
10. `test_bootstrap.py` — `bootstrap_mesh(mesh_root, agent_ids, rules_overrides=None, force_rules=False)` creates a coordinator (and thus `agents/<id>/inbox/`, `locks/`) for every id in `agent_ids`, validating each via `validate_name`; rejects `agent_ids` that collide after lowercase normalization (e.g. `agent_mbp` + `Agent_MBP`) before creating anything; writes `config/local_rules.json` via `rules_template` exactly once; raises (does not swallow) `FileExistsError` from the rules-template step when `local_rules.json` already exists and `force_rules=False`; passing `force_rules=True` overwrites it; call order is coordinator/dir creation before the rules-template write.

### Integration (smoke-level, not micro-cycled)
11. `test_bootstrap_integration.py` — one end-to-end run of `bootstrap_mesh` against `tmp_path` asserting the full real directory tree + a valid `local_rules.json`, for the three default agent ids (`agent_mac_mini`, `agent_mbp`, `agent_ollama_local`). No code-deployment shim exists or is tested — the live share is data-only.

### `mcp_server.py` (follow-up planning pass, not yet cycled)
12. Not yet TDD-cycled: this module's tool-registration/dispatch design (which coordinator methods become MCP tools, request/response shape, error mapping) needs its own design pass before it can be broken into Iron Rule cycles the way the modules above were. Placeholder only.

## Tooling setup

1. Author `pyproject.toml` by hand (repo already has content, don't `uv init` over it): `hatchling` build backend, `requires-python = ">=3.11"`, src-layout pointing at `src/agent_mesh_core`.
2. Dev deps via `uv add --dev pytest ruff` once the file exists.
3. `[project.scripts]` entry: `agent-mesh-bootstrap = "agent_mesh_core.bootstrap:main"` (what `deploy.sh` invokes). An `mcp_server.py` entry point will be added once that module's design pass lands.
4. `[tool.pytest.ini_options] testpaths = ["tests"]`; `[tool.ruff]` with `select = ["E", "F", "I"]`.
5. `.gitignore` (already applied — see repo's `.gitignore`): runtime paths (`.tmp_*`, `*.lock`, `agents/`, `locks/`, `config/*.json` except `*.template.json`), plus standard Python/OS ignores — never track the live execution directory.
6. `uv sync`, then `uv run pytest` / `uv run ruff check .` as the ongoing dev loop.
7. `deploy.sh` — a thin, single-purpose, *local* wrapper (not a TDD cycle): run on the Mac mini, which already has this repo cloned/updated and `uv sync`'d, with `/Users/Shared/AgentMesh` as a local path (no mount involved). It runs exactly one command: `uv run agent-mesh-bootstrap --mesh-root /Users/Shared/AgentMesh --agent-ids agent_mac_mini,agent_mbp,agent_ollama_local`. All the logic `deploy.sh` depends on (directory creation, refuse-to-overwrite config, duplicate-ID rejection) is already covered by `test_bootstrap.py` and lower-level unit tests.

## Verification

- `uv run pytest -v` — full suite green, including the thread-pool lock race (run a few times to confirm it's not flaky).
- `uv run ruff check .` — clean.
- Manual smoke: instantiate `AgentMeshCoordinator` twice against the same `tmp_path`-like real directory outside pytest (e.g. a scratch dir), exercise `send_message` + inbox scan across the pair, confirm no leftover `.tmp_*` files.
- Manual smoke: run `deploy.sh` against a scratch directory (not the real `/Users/Shared/AgentMesh`) to confirm it produces the same tree `test_bootstrap_integration.py` asserts, then re-run it to confirm `local_rules.json` is left untouched (no `force_rules`).
- Manual smoke: simulate each of the four crash points by hand (empty `.processing/<claim_id>/`; message present with no sidecar; message present with a malformed sidecar; complete claim), confirm `scan_and_clear_inbox` leaves all four alone, then confirm `recover_processing` handles each correctly (dry-run report, then `requeue`/`quarantine`, including the destination-collision-raises case) both via age threshold and via explicit `claim_ids`. Confirm a *fresh* empty claim dir (simulating a live scanner mid-claim) is left alone by a default-threshold `recover_processing` call.
- Manual smoke: force a lock-token-write failure and confirm `acquire_lock` leaves no orphaned lock dir; manually place an extra file in an otherwise-releasable lock dir and confirm `release_lock` raises instead of deleting it.
- Not yet covered here: end-to-end verification of the MCP server itself (tool registration reachable from a real Claude Code/Codex client over Tailscale) and the Ollama HTTP wrapper — both follow once `mcp_server.py`'s design pass lands.
