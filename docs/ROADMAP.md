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
**Stack**: Python 3.11+, uv-managed package, pytest + ruff, FastMCP 2.x (streamable HTTP) + Starlette/uvicorn
**Status**: Deployed — MCP server and Ollama HTTP wrapper both built, tested, and verified end-to-end against a real Mac mini + MBP pair over Tailscale, and both now run as persistent `launchd` services on the Mac mini.

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
| ~~**TASK-10**~~ | ✅ **Operational readiness: launchd plist, logging, startup validation** | **P2** | ✅ DONE (2026-07-24) | FEATURE-8 |
| ~~**TASK-11**~~ | ✅ **Deploy to Mac mini, register with Claude Code/Codex over Tailscale, verify end-to-end** | **P1** | ✅ DONE (2026-07-23) | FEATURE-8, TASK-10 |
| ~~**TASK-12**~~ | ✅ **Persistent launchd service for the Ollama HTTP wrapper** | **P2** | ✅ DONE (2026-07-23) | TASK-11 |
| ~~**TASK-13**~~ | ✅ **README.md: install/run on new Mac, Linux, Windows machines + Ollama integration steps** | **P2** | ✅ DONE (2026-07-24) | TASK-11 |
| ~~**TASK-14**~~ | ✅ **Public-release readiness: security, license, examples, personal-data scrub** | **P2** | ✅ DONE (2026-07-23) | TASK-13 |
| ~~**TASK-15**~~ | ✅ **Ollama task-routing example: reference poller + integration docs** | **P3** | ✅ DONE (2026-07-23) | TASK-9 |

## Active Work

No open tasks. See `## Completed` below or run `/waypoint:add` to file new work.

## Completed

### ~~TASK-15~~: Ollama task-routing example: reference poller + integration docs (✅ DONE)
**Priority**: P3
**Status**: ✅ DONE (2026-07-23)

Added `examples/ollama/mesh_poller.py`, a stdlib-only reference poller
closing the loop `README.md`'s "Ollama Integration" section previously
flagged as unbuilt follow-up work: it claims `agent_ollama_local`'s
inbox via `POST /claim_inbox_messages`, routes `mesh.ollama.task`
messages to a local Ollama server's `/api/generate`, replies to the
sender (or an explicit `reply_to`) via `POST /send_message`, and
acknowledges every claim via `POST /acknowledge_claims` — the same
claim-then-acknowledge contract every other caller uses, just driven
from outside the mesh over the HTTP wrapper. No new dependency: uses
`urllib` rather than adding `requests`, matching the minimal footprint
in `pyproject.toml`.

`examples/ollama/README.md` documents the task-routing judgment call
this is meant to demonstrate — route high-volume, low-stakes work
(bulk summarization, the poll loop itself, draft-then-review,
inbox pre-filtering/triage) to the zero-marginal-cost, no-session-limit
local model, and keep anything correctness-critical (logic changes,
anything touching the lock/claim/atomic-write invariants) on Claude
Code/Codex. `README.md`'s "Ollama Integration" section now links to both
files instead of describing the wrapper as unbuilt.

Explicitly out of scope here (unchanged from TASK-13's framing): this is
example code the operator runs or adapts manually, not a `launchd`-managed
always-on service — turning it into one, if wanted, is separate follow-up
work, not something this task silently expanded into.

**Tasks**:
- [x] Confirm the exact `http_server.py` routes/payload shapes (`dispatch.py`) before writing example code against them, rather than guessing
- [x] Write a reference poller demonstrating claim → route to Ollama → reply → acknowledge, using only the stdlib
- [x] Document the task-routing rationale (what's a good fit for local Ollama vs. what stays on a paid-session agent) alongside the example
- [x] Update `README.md`'s "Ollama Integration" section to point at the example instead of describing the wrapper as unbuilt

### ~~TASK-14~~: Public-release readiness: security, license, examples, personal-data scrub (✅ DONE)
**Priority**: P2
**Status**: ✅ DONE (2026-07-23)

Added `LICENSE` (MIT) and `SECURITY.md`, the latter stating the trust model
explicitly: one operator, trusted callers only, private Tailscale network as
the sole boundary, no authentication/authorization/anti-spoofing at the app
layer, and what the filesystem/locking layer does still defend against
regardless of that model. Scrubbed the one remaining personal path
(`/Users/jacobmorris/Library/Logs/agent-mesh-core` → `~/Library/Logs/agent-mesh-core`)
from `docs/OPERATIONS.md`; confirmed `README.md` (written under `TASK-13`)
already used `<mac-mini-tailscale-host>`-style placeholders throughout, so
no further scrubbing was needed there. Added a "Status & Support" section
and a License section to `README.md`. Left `com.jacobmorris.*` launchd
bundle IDs and historical real-IP mentions inside completed `## Completed`
write-ups as-is: the bundle ID is a reverse-DNS namespace tied to real
deployed plist filenames (renaming it is a live-deployment migration, not a
privacy fix, and Jacob's identity is already public via the repo/commit
metadata), and the historical entries are an audit trail of what was
actually deployed, not reusable setup instructions.

**Tasks**:
- [x] Add `SECURITY.md` documenting the trust boundary: one operator, trusted callers, private Tailscale network, no authentication/authorization/anti-spoofing inside the app layer
- [x] Choose and add a license file
- [x] Scrub or template personal deployment details from public-facing docs/examples, including raw Tailscale IPs, local usernames, machine names where not essential, and Jacob-specific paths
- [x] Add public-safe example config/commands that use placeholders instead of personal values
- [x] Add a status/support statement: experimental personal infrastructure, issues/PR expectations, and what is intentionally out of scope
- [x] Run a final public-readiness review over `README.md`, `SECURITY.md`, `docs/OPERATIONS.md`, roadmap, and templates before making the repository public

### ~~TASK-13~~: README.md: install/run on new Mac, Linux, Windows machines + Ollama integration steps (✅ DONE)
**Priority**: P2
**Status**: ✅ DONE (2026-07-24)

Added a root `README.md` for human onboarding. It explains what the project
is, states the single-operator/private-tailnet trust model, links to the
problem statement, implementation plan, operations guide, and roadmap, and
covers new-client setup, per-OS Tailscale notes, Mac-mini host setup,
development commands, and the current Ollama integration shape. The Ollama
section documents the real state clearly: the HTTP wrapper exists, but an
automatic Ollama-side wrapper/proxy is still follow-up integration work if
needed. Updated `AGENTS.md` so cold-start agents know the repo is
implemented and that `README.md` is the user-facing onboarding doc.

**Tasks**:
- [x] Write `README.md` covering: what this project is (link to `docs/PROBLEM_STATEMENT.md`), quick client setup (register with an already-running mesh), full dev setup (clone/sync/test), and a link out to `docs/OPERATIONS.md` for deploying/operating the Mac-mini side
- [x] Include explicit public-use framing: "personal/single-operator reference implementation", "trusted callers only", "not multi-tenant", "not secure against malicious clients", and "experimental/personal infrastructure"
- [x] Document per-OS Tailscale client setup differences (macOS/Linux/Windows) needed before any `mcp add` command will resolve the Mac mini's Tailscale IP
- [x] Investigate and document (or explicitly scope as follow-up) what's actually needed on the Ollama side to call `http_server.py`'s routes — this is the part with no existing implementation to document, treat it as a design question, not a writing task
- [x] Cross-link `README.md` from `AGENTS.md`'s "Documentation layout" section, matching how every other doc in this repo is indexed

### ~~TASK-12~~: Persistent launchd service for the Ollama HTTP wrapper (✅ DONE)
**Priority**: P2
**Status**: ✅ DONE (2026-07-23)

Mirrored the MCP server's `TASK-10` pattern rather than inventing a new one.
`agent-mesh-http-server` now shares `agent-mesh-mcp-server`'s
`validate_mesh_root` and fails fast (exit `2`, clear stderr message) if the
mesh root doesn't exist, isn't a directory, or isn't writable — closing the
review finding that `/health_check` could previously create a missing root
as a side effect. Added a sibling `render_http_launchd_plist.py` and
`com.jacobmorris.agent-mesh-core.http-server.plist.template`, same
placeholder set and `RunAtLoad`/`KeepAlive` behavior as the MCP template,
bound to port `8001` so it doesn't collide with the MCP server's `8000`.
Rendered and loaded for real on the Mac mini
(`~/Library/LaunchAgents/com.jacobmorris.agent-mesh-core.http-server.plist`,
bound to `<mac-mini-tailscale-ip>:8001`); `launchctl list` shows it running alongside
the MCP server, and a fresh `launchctl bootstrap` followed by a plain `curl
-X POST http://<mac-mini-tailscale-ip>:8001/health_check` returned a real
`{"status":"ok", ...}` response. `docs/OPERATIONS.md` now documents both
services side by side. Full test suite: 155 passing, `ruff` clean.

**Tasks**:
- [x] Add startup validation to `agent-mesh-http-server`, sharing the MCP server's mesh-root validation behavior
- [x] Add a launchd plist template for `agent-mesh-http-server`, following the existing MCP-server template's structure
- [x] Render and load it on the Mac mini bound to `<mac-mini-tailscale-ip>:8001`
- [x] Verify `/health_check` responds via plain `curl` after a fresh `launchctl bootstrap`
- [x] Update `docs/OPERATIONS.md` to cover both services, not just the MCP server

### ~~TASK-10~~: Operational readiness: launchd plist, logging, startup validation (✅ DONE)
**Priority**: P2
**Status**: ✅ DONE (2026-07-24)

Scoped for a single-operator, 2–3-machine personal mesh per
`IMPLEMENTATION_PLAN_v2.md`'s "Operational readiness" section — not a full
SRE runbook. Needed before the server runs unattended, but not before it
runs at all during development.

**Tasks**:
- [x] Write a `launchd` plist (`RunAtLoad` + `KeepAlive`) for the MCP server on the Mac mini
- [x] Redirect stdout/stderr to a log file (no rotation infra in v1)
- [x] Add startup validation: mesh root exists/is a directory/is writable, fail fast with a clear error otherwise
- [x] Verify `health_check()`'s real output against a running server

### ~~TASK-11~~: Deploy to Mac mini, register with Claude Code/Codex over Tailscale, verify end-to-end (✅ DONE)
**Priority**: P1
**Status**: ✅ DONE (2026-07-23)

Deployed for real. `deploy.sh` ran on the Mac mini against
`/Users/Shared/AgentMesh`, producing the expected tree (three agent
inboxes, `config/local_rules.json`, `locks/`). Rendered and loaded the MCP
server's `launchd` plist bound to the Mac mini's Tailscale IP
(`<mac-mini-tailscale-ip>:8000`, not the MagicDNS hostname — DNS resolution at
`launchd` boot time, before the network is fully up, is a real failure
mode a raw IP avoids). `claude mcp add --transport http` and `codex mcp
add --url` both registered the server from the MBP; `claude mcp list`
confirmed `✔ Connected`. Exercised a real `send_message` →
`claim_inbox_messages` → `acknowledge_claims` round trip from the MBP
through the live server. Started the Ollama HTTP wrapper manually
(`agent-mesh-http-server`, port 8001), confirmed the same three-call round
trip via plain `curl` — no MCP client needed — then stopped it (no
persistent service for it yet; that's optional follow-up work, not part
of this task's scope).

**Tasks**:
- [x] Run `deploy.sh` on the Mac mini against the real mesh root
- [x] Register the MCP server with Claude Code and Codex from the MBP over Tailscale
- [x] Exercise `send_message` + `claim_inbox_messages`/`acknowledge_claims` across a real pair of machines
- [x] Confirm the Ollama HTTP wrapper works from a local script on at least one non-MCP machine

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
