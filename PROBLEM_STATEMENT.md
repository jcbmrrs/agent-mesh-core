# Problem Statement

## Problem

Jacob runs multiple AI coding-assistant agents (Claude Code, Codex, and local
Ollama-backed tools) across multiple machines (an always-on Mac mini, an MBP
M3 Pro, and eventually a Linux and/or Windows box) that are on the same
Tailscale tailnet but otherwise isolated from each other. These agents have
no built-in way to:

- pass messages or task handoffs to each other,
- know what another agent/machine is currently doing (state/heartbeat),
- avoid two agents colliding on the same resource or file,
- share read-only config (rules, active model overrides) consistently.

The naive fix — a single shared mutable file or folder everyone reads and
writes — breaks under concurrent access: partial writes corrupt JSON,
"last write wins" clobbers other agents' updates, and cross-platform file
locking (macOS AFP-ish semantics vs. Linux POSIX vs. Windows oplocks) can't
be trusted to serialize access safely, especially over a network mount.

## Proposed solution (current design, per IMPLEMENTATION_PLAN.md / AGENTS.md)

A small, from-scratch Python package (`src/agent_mesh_core/`) implementing a
coordination layer over a **shared directory tree**
(`/Users/Shared/AgentMesh`, mounted by every machine via SMB over
Tailscale), built entirely around patterns designed to avoid concurrent
mutable-file access:

- **Per-agent inboxes**, not a shared queue — agents only ever write into
  *another* agent's inbox, so no two writers ever target the same path.
- **Atomic writes** everywhere (`mkstemp` → write → `fsync` → `os.replace`),
  so a message or state file is either fully old or fully new, never
  half-written.
- **Directory-creation-based locks** (`os.mkdir`/`rmdir`), the one primitive
  that's atomic on every target OS, with an ownership-token file to guard
  release — deliberately *not* file-based locks, and deliberately *no*
  automatic stale-lock breaking (that's an operator-invoked recovery step).
- **Claim-then-process inbox scanning**, so two scans of the same inbox
  can't double-handle one message, with crash recovery as an explicit,
  human-invoked operation, never automatic.
- A strict repo/live-share split: logic lives in this git repo and is
  installed independently on each machine (`git pull` + `uv sync`); the live
  share holds only data and is never git-tracked, so a bad code change is a
  `git revert` away and never touches live agent state.

Four rounds of adversarial review have hardened this design against a long
list of crash/edge cases (symlink escapes, malformed messages, claim-ID
collisions, clock skew, etc.), but none of it has been implemented yet.

## Open question raised by today's research

Two independent research passes (`SOLUTION_LANDSCAPE.md`,
`CLAUDE-SOLUTION-LANDSCAPE.md`) converge on a competing possibility worth
deciding *before* writing code: several existing open-source tools
(`swarm-protocol`, `Shire`, `guild`, `hcom`) already solve this same narrow
niche — coordinating coding-assistant CLIs across machines — by running a
**small local service** (often exposed as an MCP server, which Claude Code
and Codex already speak) rather than a mounted filesystem share. That
sidesteps an unverified assumption in the current design: whether
`os.replace`/rename is actually atomic over SMB the way it is on local
POSIX disk (classic Maildir prior art avoids bare `rename()` over network
mounts for exactly this reason).

This doesn't change *what problem* is being solved — it changes *how much
of the reviewed lock/claim/atomic-write logic still needs its
network-filesystem hardening* if the transport moves from "mounted SMB
share" to "local disk on the Mac mini, reached over Tailscale via a small
server process."

See `SOLUTION_RECOMMENDATION.md` for the synthesis of both research passes
and a concrete recommendation on this open decision.
