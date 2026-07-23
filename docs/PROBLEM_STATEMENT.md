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

## Proposed solution (current design, per IMPLEMENTATION_PLAN_v2.md / AGENTS.md)

> **Decision (2026-07-23): resolved.** Running a small always-on local
> service is acceptable. The mesh's coordination logic now runs as a local
> MCP server process on the Mac mini instead of being reached by every
> machine mounting `/Users/Shared/AgentMesh` over SMB — see "Decision" below
> and `SOLUTION_RECOMMENDATION.md`. The description immediately following
> is the design as originally reviewed (four rounds of adversarial review);
> almost all of it — the inbox/lock/atomic-write logic — carries forward
> unchanged, just running against local disk instead of a network mount.

A small, from-scratch Python package (`src/agent_mesh_core/`) implementing a
coordination layer over a **shared directory tree**
(`/Users/Shared/AgentMesh` — now local disk on the Mac mini, reached by
other machines only through the MCP server, never mounted directly), built
entirely around patterns designed to avoid concurrent mutable-file access:

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
- A strict repo/live-share split: logic lives in this git repo. **As of the
  MCP-server pivot, only the Mac mini installs and runs this package**
  (`git pull` + `uv sync`) — other machines never install it; they call it
  as MCP/HTTP clients. The live share holds only data and is never
  git-tracked, so a bad code change is a `git revert` away and never
  touches live agent state.

Four rounds of adversarial review have hardened this design against a long
list of crash/edge cases (symlink escapes, malformed messages, claim-ID
collisions, clock skew, etc.), but none of it has been implemented yet.

## Decision (2026-07-23): MCP-server pivot accepted

Two independent research passes (`SOLUTION_LANDSCAPE.md`,
`CLAUDE-SOLUTION-LANDSCAPE.md`) converged on a competing possibility:
several existing open-source tools (`swarm-protocol`, `Shire`, `guild`,
`hcom`) already solve this same narrow niche — coordinating
coding-assistant CLIs across machines — by running a **small local
service** (often exposed as an MCP server, which Claude Code and Codex
already speak) rather than a mounted filesystem share.

Jacob confirmed running a small always-on local service is acceptable, so
the project now proceeds down that route: the coordinator runs as a local
MCP server process on the Mac mini, reached by Claude Code/Codex on other
machines as a registered MCP server over Tailscale, and by Ollama-backed
tooling via a thin HTTP wrapper around the same functions. No machine
other than the Mac mini ever mounts or touches `/Users/Shared/AgentMesh`
directly.

This resolves the open question cleanly:

- It keeps almost all of the reviewed lock/claim/atomic-write logic — that
  logic now runs against local disk on the Mac mini rather than a network
  mount, so it needs *less* hardening, not more.
- It removes the previously-unverified assumption the current design
  depended on: whether `os.replace`/rename is atomic over SMB the way it
  is on local POSIX disk (classic Maildir prior art avoids bare `rename()`
  over network mounts for exactly this reason). That question no longer
  needs answering, because no rename ever crosses the network.
- It drops the SMB-provisioning scope entirely (no share needs to be
  provisioned or mounted by clients), rather than merely deferring it.

See `SOLUTION_RECOMMENDATION.md` for the full synthesis and
`IMPLEMENTATION_PLAN_v2.md` for the concrete build plan (rewritten with
this decision as its baseline, rather than a patch on the older,
now-archived `docs/archive/IMPLEMENTATION_PLAN_v1.md`).
