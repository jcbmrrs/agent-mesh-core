# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

This directory is currently **design/planning stage only** — it contains no source code, build tooling, or tests yet. The three files here (`BACKGROUND.md`, `MULTI-AGENT-GUIDE.md`, `PROMPT.md`) define the architecture for a multi-agent coordination mesh that has not been implemented on disk yet. There is no `agent_core.py`, no `config/`, `agents/`, or `locks/` directory, and no test suite to run. When asked to "implement" or "set this up," treat `PROMPT.md` as the task spec and `MULTI-AGENT-GUIDE.md` as the design doc it's derived from.

## What this system is for

`/Users/Shared/AgentMesh` is meant to become a shared coordination directory, hosted on an always-on Mac mini and exposed over SMB via Tailscale (no port forwarding — clients mount via the Mac mini's Tailscale IP/MagicDNS name). Multiple agents (Claude Code, Codex, and local Ollama instances) running on different machines (Mac mini host, MBP M3 Pro, and eventually Linux/Windows boxes) will read and write here to coordinate tasks, share settings, and exchange messages.

## Planned architecture (from MULTI-AGENT-GUIDE.md / PROMPT.md)

Design principle: **no single shared mutable file.** SMB's cross-platform locking is unreliable (AFP tags vs. POSIX vs. Windows oplocks), so the design avoids concurrent writes to one file and instead uses an isolated inbox/outbox mailbox topology plus directory-based locking:

```
AgentMesh/
├── config/
│   ├── local_rules.json      # read-only rules/config for all agents
│   └── file_trees.json       # aggregated file-tree structures of the cluster
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
- **Atomic writes only.** Never write JSON directly to its destination path. Write to a temp file in the same directory (e.g. `.tmp_<name>_<pid>`), then `shutil.move`/rename over the target — this is the only write pattern that's safe across SMB.
- **Locking is directory-creation based**, not file-based: `os.mkdir()` on a path under `locks/` is atomic on every target OS (Mac/Linux/Windows), so lock acquisition = successful `mkdir`, release = `rmdir`. Never implement locks with a plain lock *file* (`open(...,'x')`) — the design explicitly calls out that only directory creation is guaranteed atomic across the mixed-OS mount.
- **Prefer filesystem watchers over polling** (e.g. Python's `watchdog`) for reacting to new inbox messages, to avoid hammering the SMB-mounted drive from multiple machines.
- **`config/local_rules.json` is read-only for agents** — it's written only by the human operator, not by any agent process.

## Coordinator API shape (agent_core.py, per PROMPT.md)

The core coordination script is expected to be named `agent_core.py` and expose an `AgentMeshCoordinator` class, instantiated per-agent with `(mesh_root_path, agent_id)`. Expected methods:

- `acquire_lock(lock_name, timeout, retry_interval)` / `release_lock(lock_name)` — directory-based mutual exclusion under `locks/`.
- `atomic_write_json(target_file_path, data)` — temp-file-then-move write for any JSON in the mesh.
- `update_state(status, tasks, extra_metadata)` — writes this agent's own `agents/<agent_id>/state.json`.
- `send_message(target_agent_id, message_type, payload)` — atomically drops a timestamped JSON message into another agent's `inbox/`.
- An inbox-scanning function (not yet in the boilerplate) that reads and then deletes processed messages from `agents/<agent_id>/inbox/`.

## Network/transport notes

- Host and clients connect over **Tailscale**, using the Mac mini's Tailscale IP (`100.x.y.z`) or MagicDNS name — this is what avoids router port-forwarding.
- macOS clients mount via `mount_smbfs` or Finder's `Cmd+K` → `smb://100.x.y.z/AgentMesh`.
- Linux clients use `cifs-utils` with the `_netdev` mount option so systemd waits for the Tailscale interface before mounting.
- Windows clients use `net use Z: \\100.x.y.z\AgentMesh /persistent:yes`.

Any script that provisions the SMB share itself (vs. just consuming it) should prefer macOS's `sharing`/`dscl` CLI utilities over asking the user to click through System Settings, per the automation intent in `PROMPT.md`.

## Keep in sync

- TODO: list file pairs that must agree, e.g. "add a setting → document it in the README".
