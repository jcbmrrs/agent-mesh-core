# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

This directory is currently **design/planning stage only** — it contains no source code, build tooling, or tests yet. The files here (`BACKGROUND.md`, `MULTI-AGENT-GUIDE.md`, `PROMPT.md`, `PROJECT-SETUP.md`) define the architecture for a multi-agent coordination mesh that has not been implemented on disk yet. There is no `agent_core.py`, no `config/`, `agents/`, or `locks/` directory, and no test suite to run. When asked to "implement" or "set this up," treat `PROMPT.md` as the task spec (as amended by `PROJECT-SETUP.md`), `MULTI-AGENT-GUIDE.md` as the design doc it's derived from, and `IMPLEMENTATION_PLAN.md` as the concrete build plan.

## Repo vs. live share split (per PROJECT-SETUP.md)

Two distinct zones, never conflated:

- **This git repo** — source of truth for logic: the `src/agent_mesh_core/` package (see `IMPLEMENTATION_PLAN.md`), templates (`config/*.template.json`), `deploy.sh`, and the design docs. Fully version-controlled; a bad change to lock mechanics is one `git revert` away.
- **`/Users/Shared/AgentMesh`** — the live data share. Populated *from* this repo via `deploy.sh`, never edited directly and never git-tracked (see `.gitignore`). It holds runtime state only: `agents/*/inbox/`, `agents/*/state.json`, `locks/`, and the deployed `config/local_rules.json`.

Why the split: it keeps Claude Code/Codex context windows clean (no wading through megabytes of agent heartbeats or old inbox messages), makes logic bugs revertible without destroying live agent state, and lets a new machine (the Linux box, the Windows rig) get productive with its own `git clone` + `uv sync`.

`deploy.sh` should not reimplement Python logic in bash — e.g. the "don't clobber an existing `local_rules.json`" check belongs in `rules_template.write_local_rules_template`'s `force` flag (already unit-tested), not as a bash `[ -f ... ]` guard. **`deploy.sh` has exactly one job and it is local-only**: run on a machine that already has the package installed (`git pull` + `uv sync`, done separately, by that machine's operator) and the mesh root mounted, and invoke `agent-mesh-bootstrap` to populate the live share's *data*. It never distributes code to other machines and never runs remotely — that would be a materially different script with a different trust/network model, and conflating the two was a real bug in an earlier draft of this plan (see `IMPLEMENTATION_PLAN.md`'s "second adversarial review" notes).

`bootstrap_mesh`/`agent-mesh-bootstrap` (what `deploy.sh` calls) is **operator/admin tooling, not part of the runtime API** any agent process should call. It's the one thing allowed to write `local_rules.json`, and it's meant to be invoked deliberately against a specific mesh root — not wired into any agent's normal request/response loop.

## What this system is for

`/Users/Shared/AgentMesh` is meant to become a shared coordination directory, hosted on an always-on Mac mini and exposed over SMB via Tailscale (no port forwarding — clients mount via the Mac mini's Tailscale IP/MagicDNS name). Multiple agents (Claude Code, Codex, and local Ollama instances) running on different machines (Mac mini host, MBP M3 Pro, and eventually Linux/Windows boxes) will read and write here to coordinate tasks, share settings, and exchange messages.

## Planned architecture (from MULTI-AGENT-GUIDE.md / PROMPT.md)

Design principle: **no single shared mutable file.** SMB's cross-platform locking is unreliable (AFP tags vs. POSIX vs. Windows oplocks), so the design avoids concurrent writes to one file and instead uses an isolated inbox/outbox mailbox topology plus directory-based locking:

```
AgentMesh/
├── config/
│   ├── local_rules.json      # read-only rules/config for all agents
│   └── file_trees.json       # aggregated file-tree structures of the cluster (not built in v1 — see IMPLEMENTATION_PLAN.md)
├── agents/
│   ├── agent_mac_mini/
│   │   ├── inbox/            # other agents drop messages here
│   │   └── state.json        # heartbeat, active tasks, metadata
│   ├── agent_mbp/
│   │   ├── inbox/
│   │   └── state.json
│   └── agent_ollama_local/
│       ├── inbox/
│       └── state.json
└── locks/                    # directory-based mutual exclusion (mkdir-as-lock)
```

Key invariants any implementation here must preserve:

- **One inbox per agent, not a shared queue.** Each agent only ever writes into *another* agent's `inbox/`, never into a shared global file, to avoid concurrent-write collisions.
- **Atomic writes only.** Never write JSON directly to its destination path. Write to a temp file in the same directory with a collision-resistant name (`tempfile.mkstemp`, not PID-based — PIDs collide across machines), then `os.replace`/rename over the target — this is the only write pattern that's safe across SMB.
- **Locking is directory-creation based**, not file-based: `os.mkdir()` on a path under `locks/` is atomic on every target OS (Mac/Linux/Windows), so lock acquisition = successful `mkdir`, release = `rmdir`. Never implement locks with a plain lock *file* (`open(...,'x')`) — the design explicitly calls out that only directory creation is guaranteed atomic across the mixed-OS mount. **No stale-lock breaking in v1** — mtime-based staleness is unsafe under SMB clock skew and would need an ownership-token protocol to be safe; that's deferred, not silently built. `acquire_lock` writes a random token into `<lock_dir>/owner.token` and returns it inside a `LockHandle`; `release_lock(handle)` only removes the lock dir if the on-disk token still matches — a narrower, timeless fix than stale-lock breaking that specifically stops a stale handle from deleting someone else's lock after an external removal + reacquire. It does **not** attempt any lease/timeout logic. Releasing an already-released handle a second time is a deliberate no-op (convenience for `try/finally` cleanup), not proof the caller still held the lock.
- **Agent IDs, lock names, and target agent IDs are validated** before they become path components: a strict portable pattern (no separators/`..`/absolute paths), **lowercase-only** (avoids collisions on case-insensitive mounts — macOS default, Windows), and rejection of Windows-reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`).
- **`atomic_write_json` is confined to the mesh root** — it resolves `target_file_path` and rejects (raises) anything that doesn't land under `self.mesh_root`, so name validation elsewhere can't be bypassed by an arbitrary path argument.
- **Inbox messages are claimed before processing** via a single atomic `mkdir(.processing/<claim_id>/)` followed by renaming the message into it (the rename — not the `mkdir` — is what enforces exclusivity, since only one renamer can win against the shared source path) and a `.claim.json` sidecar, not just read-then-deleted, so two scans of the same inbox can't double-process one message. Malformed messages are quarantined (renamed aside), never left in place for a re-scan to rediscover forever. A crashed/killed claimant leaves its claim in `.processing/<claim_id>/` in one of three identifiable states (empty dir, message-without-sidecar, or a complete claim) — recoverable only via an explicit, operator-invoked `recover_processing(older_than_seconds | claim_ids, action)` call, never automatically (same reasoning as no automatic stale-lock breaking). The age threshold is a heuristic, not a correctness guarantee, given cross-machine clock skew — `claim_ids` is the clock-skew-proof override.
- **Message ordering is best-effort filename order only — no cross-machine causal or wall-clock guarantee.** Clocks skew and drift across machines; don't build logic that assumes strict delivery order without an explicit per-sender sequence number (not built in v1, since nothing currently needs it).
- **Filesystem watchers are a v2 concern, not v1.** v1 ships polling-only (`scan_and_clear_inbox`); prefer watchers (e.g. Python's `watchdog`) over tighter polling loops once there's an actual latency need, to avoid hammering the SMB-mounted drive from multiple machines.
- **`config/local_rules.json` is read-only for agents** — it's written only by the human operator (via `bootstrap_mesh`/`deploy.sh`), not by any agent process at runtime. The same single-writer rule applies to `file_trees.json` whenever it's eventually built.

## Coordinator API shape (`src/agent_mesh_core/`, per PROMPT.md and IMPLEMENTATION_PLAN.md)

`PROMPT.md` names a deployed `/Users/Shared/AgentMesh/agent_core.py` — that's superseded (see "Repo vs. live share split" above): the real package is `src/agent_mesh_core/`, an `AgentMeshCoordinator` class in `coordinator.py`, instantiated per-agent with `(mesh_root_path, agent_id)`. Expected surface:

- `validate_name(name)` (`names.py`) — rejects anything unsafe as a path component (separators, `..`, uppercase, Windows-reserved names); called by every method below before touching a name-derived path.
- `acquire_lock(lock_name, timeout, retry_interval) -> LockHandle | None` / `release_lock(handle)` — directory-based mutual exclusion under `locks/`, with a token written into `<lock_dir>/owner.token` and checked on release. No stale-lock breaking, no lease/timeout logic in v1.
- `atomic_write_json(target_file_path, data)` — confined under `self.mesh_root`; `mkstemp` → write → flush → `fsync` → close → `os.replace` → best-effort parent-dir fsync, for any JSON in the mesh.
- `update_state(status, tasks, extra_metadata)` — writes this agent's own `agents/<agent_id>/state.json`.
- `send_message(target_agent_id, message_type, payload)` — atomically drops a timestamped JSON message into another agent's `inbox/`; requires the target inbox to actually be a directory (fails closed on a file or symlink there).
- `scan_and_clear_inbox` (`inbox.py`) — claims each message into `.processing/<claim_id>/` (`mkdir` + rename + `.claim.json` sidecar), then reads/deletes it; quarantines malformed JSON into `.invalid/` instead of leaving it in place. Ordering is best-effort filename order only.
- `recover_processing(mesh_root, agent_id, older_than_seconds=None, claim_ids=None, action=None)` (`inbox.py`) — operator-invoked only, never automatic; reports, requeues, or quarantines claims left behind by a crashed/killed claimant, selected by age heuristic or by explicit `claim_ids`.
- `bootstrap_mesh` (`bootstrap.py`) — operator/admin tooling: wires coordinator init + `local_rules.json` templating for a set of agent IDs (rejecting duplicate IDs after lowercase normalization); what `deploy.sh` actually calls. Not part of the runtime API.

## Network/transport notes

- Host and clients connect over **Tailscale**, using the Mac mini's Tailscale IP (`100.x.y.z`) or MagicDNS name — this is what avoids router port-forwarding.
- macOS clients mount via `mount_smbfs` or Finder's `Cmd+K` → `smb://100.x.y.z/AgentMesh`.
- Linux clients use `cifs-utils` with the `_netdev` mount option so systemd waits for the Tailscale interface before mounting.
- Windows clients use `net use Z: \\100.x.y.z\AgentMesh /persistent:yes`.

`smb_provision.py` is a dry-run command generator/validator (prefers macOS's `sharing`/`dscl` CLI utilities over asking the user to click through System Settings, per the automation intent in `PROMPT.md`) — it constructs and unit-tests command argument lists, it does not itself perform real SMB provisioning. Actual execution is a manual step on the Mac mini.

## Keep in sync

- `MULTI-AGENT-GUIDE.md` (directory structure + `agent_core.py` boilerplate) ↔ this file's "Planned architecture" and "Coordinator API shape" sections — if the boilerplate class/method signatures change, update the summary here too.
- `PROMPT.md` (task spec, as amended) ↔ `IMPLEMENTATION_PLAN.md` — if the scope in PROMPT.md changes (e.g. dropping the SMB provisioning step), the Logic Gate triage and TDD cycle list in the plan need to change with it.
- `BACKGROUND.md` (Q&A on hosts/agents/OSes) ↔ this file's "Network/transport notes" — if the set of client machines/OSes changes, update both the Q&A answers and the transport notes.
- `PROJECT-SETUP.md` (`deploy.sh`, `.gitignore` recommendations) ↔ this repo's actual `.gitignore` and `IMPLEMENTATION_PLAN.md`'s "Deployment" section — if the deploy mechanism or ignored-path list changes in one, update the other.
- `PLAN_FEEDBACK.md` / `PLAN_FEEDBACK-2.md` / `PLAN_FEEDBACK-3.md` (adversarial reviews) ↔ `IMPLEMENTATION_PLAN.md`'s "Resolved after..." sections and this file's invariants — if a future review lands, add its resolutions the same way rather than editing history away.
- The **superseded banners and inline "(historical, superseded)" markers** in `MULTI-AGENT-GUIDE.md`, `PROJECT-SETUP.md`, and `PROMPT.md` ↔ whatever `IMPLEMENTATION_PLAN.md` currently says supersedes them — if the v1 design changes again, update both the top banners and the inline markers, don't just let them go stale.
