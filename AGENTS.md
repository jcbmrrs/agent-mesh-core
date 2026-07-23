# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

This directory is currently **design/planning stage only** — it contains no source code, build tooling, or tests yet. The files here (`BACKGROUND.md`, `MULTI-AGENT-GUIDE.md`, `PROMPT.md`, `PROJECT-SETUP.md`) define the architecture for a multi-agent coordination mesh that has not been implemented on disk yet. There is no `agent_core.py`, no `config/`, `agents/`, or `locks/` directory, and no test suite to run. When asked to "implement" or "set this up," treat `PROMPT.md` as the task spec (as amended by `PROJECT-SETUP.md`), `MULTI-AGENT-GUIDE.md` as the design doc it's derived from, and `IMPLEMENTATION_PLAN.md` as the concrete build plan.

## Repo vs. live share split (per PROJECT-SETUP.md)

Two distinct zones, never conflated:

- **This git repo** — source of truth for logic: the `src/agent_mesh_core/` package (see `IMPLEMENTATION_PLAN.md`), templates (`config/*.template.json`), `deploy.sh`, and the design docs. Fully version-controlled; a bad change to lock mechanics is one `git revert` away.
- **`/Users/Shared/AgentMesh`** — the live data share. Populated *from* this repo via `deploy.sh`, never edited directly and never git-tracked (see `.gitignore`). It holds runtime state only: `agents/*/inbox/`, `agents/*/state.json`, `locks/`, and the deployed `config/local_rules.json`.

Why the split: it keeps Claude Code/Codex context windows clean (no wading through megabytes of agent heartbeats or old inbox messages), makes logic bugs revertible without destroying live agent state, and lets a new machine (the Linux box, the Windows rig) get productive with a `git clone` + mount + `deploy.sh` run.

`deploy.sh` should not reimplement Python logic in bash — e.g. the "don't clobber an existing `local_rules.json`" check belongs in `rules_template.write_local_rules_template`'s `force` flag (already unit-tested), not as a bash `[ -f ... ]` guard. `deploy.sh`'s job is limited to: sync the repo's `src/` to the target machine (or rely on it already being there via `git pull`), then invoke the packaged bootstrap entrypoint.

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
- **Locking is directory-creation based**, not file-based: `os.mkdir()` on a path under `locks/` is atomic on every target OS (Mac/Linux/Windows), so lock acquisition = successful `mkdir`, release = `rmdir`. Never implement locks with a plain lock *file* (`open(...,'x')`) — the design explicitly calls out that only directory creation is guaranteed atomic across the mixed-OS mount. **No stale-lock breaking in v1** — mtime-based staleness is unsafe under SMB clock skew and would need an ownership-token protocol to be safe; that's deferred, not silently built.
- **Agent IDs, lock names, and target agent IDs are validated** before they become path components (strict portable pattern, no separators/`..`/absolute paths) — they're attacker- or typo-controlled inputs that would otherwise let a bad name escape the mesh root.
- **Inbox messages are claimed before processing** (atomic rename into a `.processing/` subdir), not just read-then-deleted, so two scans of the same inbox can't double-process one message. Malformed messages are quarantined (renamed aside), never left in place for a watcher/re-scan to rediscover forever.
- **Filesystem watchers are a v2 concern, not v1.** v1 ships polling-only (`scan_and_clear_inbox`); prefer watchers (e.g. Python's `watchdog`) over tighter polling loops once there's an actual latency need, to avoid hammering the SMB-mounted drive from multiple machines.
- **`config/local_rules.json` is read-only for agents** — it's written only by the human operator, not by any agent process. The same single-writer rule applies to `file_trees.json` whenever it's eventually built.

## Coordinator API shape (`src/agent_mesh_core/`, per PROMPT.md and IMPLEMENTATION_PLAN.md)

`PROMPT.md` names a deployed `/Users/Shared/AgentMesh/agent_core.py` — that's superseded (see "Repo vs. live share split" above): the real package is `src/agent_mesh_core/`, an `AgentMeshCoordinator` class in `coordinator.py`, instantiated per-agent with `(mesh_root_path, agent_id)`. Expected surface:

- `validate_name(name)` (`names.py`) — rejects anything unsafe as a path component; called by every method below before touching a name-derived path.
- `acquire_lock(lock_name, timeout, retry_interval)` / `release_lock(lock_name)` — directory-based mutual exclusion under `locks/`. No stale-lock breaking in v1.
- `atomic_write_json(target_file_path, data)` — temp-file-then-move write for any JSON in the mesh.
- `update_state(status, tasks, extra_metadata)` — writes this agent's own `agents/<agent_id>/state.json`.
- `send_message(target_agent_id, message_type, payload)` — atomically drops a timestamped JSON message into another agent's `inbox/`.
- `scan_and_clear_inbox` (`inbox.py`) — claims each message via atomic rename into `.processing/`, then reads/deletes it; quarantines malformed JSON instead of leaving it in place.
- `bootstrap_mesh` (`bootstrap.py`) — wires coordinator init + `local_rules.json` templating for a set of agent IDs; what `deploy.sh` actually calls.

## Network/transport notes

- Host and clients connect over **Tailscale**, using the Mac mini's Tailscale IP (`100.x.y.z`) or MagicDNS name — this is what avoids router port-forwarding.
- macOS clients mount via `mount_smbfs` or Finder's `Cmd+K` → `smb://100.x.y.z/AgentMesh`.
- Linux clients use `cifs-utils` with the `_netdev` mount option so systemd waits for the Tailscale interface before mounting.
- Windows clients use `net use Z: \\100.x.y.z\AgentMesh /persistent:yes`.

Any script that provisions the SMB share itself (vs. just consuming it) should prefer macOS's `sharing`/`dscl` CLI utilities over asking the user to click through System Settings, per the automation intent in `PROMPT.md`.

## Keep in sync

- `MULTI-AGENT-GUIDE.md` (directory structure + `agent_core.py` boilerplate) ↔ this file's "Planned architecture" and "Coordinator API shape" sections — if the boilerplate class/method signatures change, update the summary here too.
- `PROMPT.md` (task spec, as amended) ↔ `IMPLEMENTATION_PLAN.md` — if the scope in PROMPT.md changes (e.g. dropping the SMB provisioning step), the Logic Gate triage and TDD cycle list in the plan need to change with it.
- `BACKGROUND.md` (Q&A on hosts/agents/OSes) ↔ this file's "Network/transport notes" — if the set of client machines/OSes changes, update both the Q&A answers and the transport notes.
- `PROJECT-SETUP.md` (`deploy.sh`, `.gitignore` recommendations) ↔ this repo's actual `.gitignore` and `IMPLEMENTATION_PLAN.md`'s "Deployment" section — if the deploy mechanism or ignored-path list changes in one, update the other.
