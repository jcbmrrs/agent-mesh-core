# ROADMAP

> AI-native task tracking. Managed by the [waypoint](https://github.com/jcbmrrs/waypoint) plugin.
>
> **Quick start**: `/waypoint:add` to add a task, `/waypoint:next` to pick one, `/waypoint:done` when finished.

## Project Overview

`agent-mesh-core` is a multi-agent coordination mesh: a shared directory on
an always-on Mac mini where Claude Code, Codex, and local Ollama instances
on different machines exchange JSON messages and state via per-agent
inboxes, directory-based locks, and atomic writes — reached by other
machines through an MCP server (and an HTTP wrapper for Ollama tooling)
rather than a mounted share. See `docs/IMPLEMENTATION_PLAN_v2.md` for the
full design and `docs/PROBLEM_STATEMENT.md` for why.

**Project**: agent-mesh-core
**Stack**: Python 3.11+, uv-managed package, pytest + ruff, MCP (server TBD)
**Status**: In Development — filesystem core built and hardened; MCP layer not yet built

## Roadmap

| ID | Title | Priority | Status | Dependencies |
|----|-------|----------|--------|--------------|
| ~~**TASK-1**~~ | ✅ **Problem statement, solution research, MCP-server pivot decision** | **P1** | ✅ DONE (2026-07-23) | - |
| ~~**TASK-2**~~ | ✅ **IMPLEMENTATION_PLAN v1 + four adversarial review rounds** | **P1** | ✅ DONE (2026-07-23) | TASK-1 |
| ~~**TASK-3**~~ | ✅ **Rewrite plan as v2 around the MCP-server pivot; archive v1** | **P1** | ✅ DONE (2026-07-23) | TASK-2 |
| ~~**TASK-4**~~ | ✅ **IMPLEMENTATION_PLAN v2 hardening: three adversarial review rounds** | **P1** | ✅ DONE (2026-07-23) | TASK-3 |
| ~~**TASK-5**~~ | ✅ **Build core TDD package (names, coordinator, inbox, rules_template, bootstrap)** | **P1** | ✅ DONE (2026-07-23) | TASK-4 |
| ~~**TASK-6**~~ | ✅ **Adversarial code review of TDD build + hardening fixes** | **P1** | ✅ DONE (2026-07-23) | TASK-5 |
| ~~**TASK-7**~~ | ✅ **Select MCP server framework/SDK, pass the framework-selection gate** | **P1** | ✅ DONE (2026-07-23) | TASK-6 |
| ~~**FEATURE-8**~~ | ✅ **Build mcp_server.py: wrap coordinator/inbox/rules_template as MCP tools** | **P1** | ✅ DONE (2026-07-23) | TASK-7 |
| ~~**TASK-9**~~ | ✅ **Build Ollama HTTP wrapper sharing mcp_server.py's dispatch layer** | **P2** | ✅ DONE (2026-07-23) | FEATURE-8 |
| **TASK-10** | **Operational readiness: launchd plist, logging, startup validation** | **P2** | IN PROGRESS (2026-07-24) | FEATURE-8 |
| **TASK-11** | **Deploy to Mac mini, register with Claude Code/Codex over Tailscale, verify end-to-end** | **P1** | PLANNED | FEATURE-8, TASK-10 |

## Active Work

### TASK-10: Operational readiness: launchd plist, logging, startup validation (IN PROGRESS)
**Priority**: P2
**Status**: IN PROGRESS (2026-07-24)

Scoped for a single-operator, 2–3-machine personal mesh per
`IMPLEMENTATION_PLAN_v2.md`'s "Operational readiness" section — not a full
SRE runbook. Needed before the server runs unattended, but not before it
runs at all during development.

**Tasks**:
- [x] Write a `launchd` plist (`RunAtLoad` + `KeepAlive`) for the MCP server on the Mac mini
- [x] Redirect stdout/stderr to a log file (no rotation infra in v1)
- [x] Add startup validation: mesh root exists/is a directory/is writable, fail fast with a clear error otherwise
- [x] Verify `health_check()`'s real output against a running server

### TASK-11: Deploy to Mac mini, register with Claude Code/Codex over Tailscale, verify end-to-end (PLANNED)
**Priority**: P1
**Status**: PLANNED (2026-07-23)

High priority — this is the actual goal of the whole project: agents on
different machines coordinating through the mesh for real, not just a
tested local library. Depends on the MCP server existing and having a
supervised way to run.

**Tasks**:
- [ ] Run `deploy.sh` on the Mac mini against the real mesh root
- [ ] Register the MCP server with Claude Code and Codex from the MBP over Tailscale
- [ ] Exercise `send_message` + `claim_inbox_messages`/`acknowledge_claims` across a real pair of machines
- [ ] Confirm the Ollama HTTP wrapper works from a local script on at least one non-MCP machine

## Completed

### ~~TASK-1~~: Problem statement, solution research, MCP-server pivot decision (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Wrote `PROBLEM_STATEMENT.md`, researched the solution landscape from two
independent angles, and resolved the transport question: the coordinator
runs as an MCP server on the Mac mini instead of every machine mounting the
mesh root over SMB.

**Tasks**:
- [x] Write `PROBLEM_STATEMENT.md`
- [x] Independent + adversarial solution-landscape research
- [x] Decide: MCP server over Tailscale, not a mounted SMB share

### ~~TASK-2~~: IMPLEMENTATION_PLAN v1 + four adversarial review rounds (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Wrote the original TDD-first implementation plan for the SMB-mount design
and hardened it across four rounds of adversarial review (lock ownership
tokens, atomic claim-then-process inbox handling, path/symlink
confinement, name validation, and more).

**Tasks**:
- [x] Write `IMPLEMENTATION_PLAN.md` (v1)
- [x] Four rounds of adversarial review and resolution

### ~~TASK-3~~: Rewrite plan as v2 around the MCP-server pivot; archive v1 (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Replaced the SMB-era plan with `IMPLEMENTATION_PLAN_v2.md`, restating the
MCP-server transport as the baseline rather than a patch, while carrying
every reviewed correctness decision forward unchanged. Archived v1 and its
four review rounds.

**Tasks**:
- [x] Write `IMPLEMENTATION_PLAN_v2.md`
- [x] Archive v1 and `PLAN_FEEDBACK.md`–`PLAN_FEEDBACK-4.md`
- [x] Reorganize docs into `docs/` and `docs/archive/`

### ~~TASK-4~~: IMPLEMENTATION_PLAN v2 hardening: three adversarial review rounds (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Hardened v2 across three more adversarial rounds: designed the MCP/HTTP
API boundary (identity model, lock-handle serialization, claim/acknowledge
split, error mapping) and operational readiness, then tightened claim-ID
validation, claim tokens, batch/size bounds, and recovery cleanup
semantics.

**Tasks**:
- [x] Design the MCP/HTTP API boundary and operational readiness
- [x] Add claim-ID validation, claim tokens, `max_messages`/size bounds
- [x] Precision-fix sidecar-write-failure, health-check shape, and cleanup semantics

### ~~TASK-5~~: Build core TDD package (names, coordinator, inbox, rules_template, bootstrap) (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Built the installable, uv-managed Python package per `IMPLEMENTATION_PLAN_v2.md`:
name/claim-ID validation, lock/atomic-write/messaging coordinator logic,
claim-then-acknowledge inbox handling with crash recovery, the
`local_rules.json` template read/writer, and the bootstrap entrypoint.

**Tasks**:
- [x] `names.py`, `coordinator.py`, `inbox.py`, `rules_template.py`, `bootstrap.py`
- [x] Full TDD test suite (112 tests passing), `ruff` clean
- [x] `deploy.sh` and console scripts (`agent-mesh-bootstrap`, `agent-mesh-recover-processing`)

### ~~TASK-6~~: Adversarial code review of TDD build + hardening fixes (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Reviewed the built package against the plan, found two real bugs
(`acknowledge_claims` could crash a whole batch on an unexpected extra
file; `recover_processing` never cleaned up an empty claim directory) plus
several test-coverage gaps and an undocumented API parameter, then fixed
all of them with new regression tests.

**Tasks**:
- [x] Adversarial review, findings in `docs/archive/PLAN_FEEDBACK-v2-4.md`
- [x] Fix `acknowledge_claims` batch-abort bug and empty-claim-dir cleanup gap
- [x] Remove undocumented `claimant_agent_id` parameter
- [x] Add concurrency, boundary, and negative-assertion tests (120 tests passing)

### ~~TASK-7~~: Select MCP server framework/SDK, pass the framework-selection gate (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Evaluated the official `mcp` SDK's built-in `FastMCP` against FastMCP 2.x
(`fastmcp`, jlowin/PrefectHQ) over streamable HTTP, against the gate
`IMPLEMENTATION_PLAN_v2.md`'s "MCP/HTTP API design" section defined.
Decided on **FastMCP 2.x over streamable HTTP**: both pass the gate, but
FastMCP 2.x has the cleaner error-mapping story (`ToolError` vs. masked
generic exceptions, mapping directly onto the "let it raise, map at the
boundary" rule) and is currently stable, while the official SDK is
mid-major-rework. Confirmed both Claude Code (`claude mcp add --transport
http`) and Codex (`codex mcp add --url`) register remote MCP servers over
streamable HTTP the same way. Full rationale recorded in
`IMPLEMENTATION_PLAN_v2.md`'s "MCP/HTTP API design" section.

**Tasks**:
- [x] Evaluate candidate MCP server libraries/SDKs against the gate: binding to a specific interface (the Mac mini's Tailscale IP, not just localhost/all-interfaces), timeout/cancellation semantics for a long-running `claim_inbox_messages` call, partial/streamed result support, how it serializes/reports tool-raised errors, and whether it supports the registration path Claude Code and Codex expect
- [x] Record the decision and rationale in `IMPLEMENTATION_PLAN_v2.md`

### ~~FEATURE-8~~: Build mcp_server.py: wrap coordinator/inbox/rules_template as MCP tools (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Built `src/agent_mesh_core/mcp_server.py`: `build_server(mesh_root) ->
FastMCP` exposes exactly the eight documented tools over FastMCP 2.x's
streamable HTTP transport, backed by a `CoordinatorRegistry` that caches
one `AgentMeshCoordinator` per `agent_id` and reuses it across calls.
Exceptions map to `fastmcp.exceptions.ToolError` at the boundary via
`_map_tool_errors`, carrying the real message through rather than
FastMCP's default masked fallback. Along the way, moved `health_check`
from `AgentMeshCoordinator` to the identity-free `MeshJsonWriter` base
class — it never used `self.agent_id`, and leaving it on
`AgentMeshCoordinator` would have meant the `health_check` tool creating a
synthetic agent directory as a side effect of every call. New console
script `agent-mesh-mcp-server`. Full test suite: 129 passing, `ruff`
clean.

**Tasks**:
- [x] Expose `acquire_lock`/`release_lock`, `update_state`, `send_message`, `claim_inbox_messages`, `acknowledge_claims`, `read_local_rules`, and `health_check` as MCP tools (never `atomic_write_json`, `recover_processing`, or `bootstrap_mesh`)
- [x] Wire the "let it raise, map at the boundary" error-mapping rule for each tool
- [x] Add an `agent-mesh-mcp-server` console script entry point
- [x] TDD-cycle each tool (`test_mcp_server.py`), now that the framework is chosen

### ~~TASK-9~~: Build Ollama HTTP wrapper sharing mcp_server.py's dispatch layer (✅ DONE)
**Priority**: P2
**Status**: ✅ DONE (2026-07-23)

Built `src/agent_mesh_core/http_server.py`: `build_app(mesh_root) ->
Starlette` exposes exactly the eight documented operations as POST routes
(`/acquire_lock`, `/release_lock`, `/update_state`, `/send_message`,
`/claim_inbox_messages`, `/acknowledge_claims`, `/read_local_rules`,
`/health_check`), each calling `MeshDispatch` directly with no new
coordinator/inbox call logic — the `dispatch.py` extraction from FEATURE-8
paid off exactly as intended, and this landed with zero changes to
`mcp_server.py` despite TASK-10 editing that same file concurrently.
`MeshDispatch`'s unmapped exceptions are mapped to HTTP status codes at
this wrapper's own boundary (`ValueError` → 400, `FileNotFoundError` →
404, `NotADirectoryError`/`FileExistsError` → 409) — the same
"let it raise, map at the boundary" rule `mcp_server.py` applies for
`ToolError`, just a different target shape. `starlette`/`uvicorn` were
already transitive deps via `fastmcp`; added as direct dependencies since
this module imports them directly. New console script
`agent-mesh-http-server` (`--mesh-root`, `--host`, `--port` — bind to the
Mac mini's Tailscale interface at deploy time, same as the MCP server;
actual deployment is `TASK-11`'s job). Full test suite: 149 passing,
`ruff` clean.

**Tasks**:
- [x] Stand up HTTP routes mirroring `dispatch.EXPOSED_OPERATIONS`, calling `MeshDispatch` directly (no new coordinator/inbox call logic)
- [x] Map `MeshDispatch`'s unmapped exceptions to HTTP status codes at this wrapper's own boundary
- [x] Bind to the Mac mini's Tailscale interface, same as the MCP server (CLI supports `--host`/`--port`; real deployment is `TASK-11`)
