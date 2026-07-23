# Adversarial Review Feedback for `IMPLEMENTATION_PLAN_v2.md`

> **Archived (2026-07-23) — historical record.** Findings 4, 8, 9, 10, 11 and part of 1/2/3/5/6 were accepted and folded directly into `../IMPLEMENTATION_PLAN_v2.md` (new "MCP/HTTP API design" and "Operational readiness" sections, the inbox claim/acknowledge split, the versioned message envelope, `read_local_rules`, and the `deploy.sh` env-var override). Findings 3, 6, and 7 were partially pushed back on: full anti-spoofing/session authorization and `openat`-style TOCTOU hardening were judged out of scope given the trust model (a single-operator, 2–3-machine personal mesh reachable only over Jacob's own Tailscale tailnet) — v2 now states that trust boundary explicitly rather than leaving it implicit. Kept for the reasoning trail, not as living guidance.

Review date: 2026-07-23

## Findings

### 1. High: MCP server design is postponed even though it is now the product boundary

`docs/IMPLEMENTATION_PLAN_v2.md` says `mcp_server.py` and the HTTP wrapper are "not yet cycled" and leaves them as a placeholder. That was acceptable when the Python package itself was the runtime API, but after the MCP pivot, correctness depends on tool identity, request mapping, authorization, handle serialization, error mapping, and deployment lifecycle.

The current plan could produce a well-tested local library that still cannot safely operate as the promised cross-machine mesh.

### 2. High: Lock handles do not have a defined remote/session lifecycle

The core design returns a `LockHandle` object from `acquire_lock` and passes it back to `release_lock`. Over MCP/HTTP, that object becomes serialized data.

The plan does not specify:

- whether the ownership token is returned to clients,
- whether clients can spoof another lock release,
- whether lock ownership is bound to caller identity or session,
- how lost client state is handled.

If the token is opaque but fully client-held, any caller with the token can release the lock. If it is server-held, the plan needs a lock registry and restart behavior.

### 3. High: Caller identity is assumed but not designed

The coordinator is described as instantiated per-agent with `(mesh_root_path, agent_id)`, while v2 says remote clients call the Mac mini MCP server. The plan does not specify how an MCP/HTTP request is associated with an `agent_id`.

Open questions:

- Can a client call `update_state` as `agent_mac_mini`?
- Can a client scan another agent's inbox?
- Can a client send messages with a forged `sender`?

The filesystem code validates path components, but it does not solve authorization or impersonation. This needs to be part of the MCP design before implementation, not after.

### 4. Medium-high: `scan_and_clear_inbox` semantics are underspecified for real agent consumption

The plan says inbox scanning claims, reads, deletes, and returns messages. That makes delivery effectively "pop all currently visible messages."

There is no specified:

- limit,
- filter,
- batch size,
- max payload size,
- acknowledgement model.

If a remote MCP call succeeds server-side but the client connection fails before the response is consumed, messages are deleted and lost. If at-most-once delivery is intentional, say so explicitly. If not, the plan needs ack/delete-after-ack or a retained processed log.

### 5. Medium-high: No durability or recovery story exists for the MCP server process itself

The design accepts hard-crash limitations inside lock creation and inbox claiming, with operator recovery. But the new architecture is a persistent daemon.

The plan should specify:

- launchd/systemd setup,
- restart policy,
- logging,
- health checks,
- startup validation of mesh root permissions,
- how operators discover stale locks and processing claims.

Otherwise "manual cleanup" has no operational path.

### 6. Medium: The plan overstates "no concurrent writers" after the MCP pivot

The pivot removes network filesystem risk because only the Mac mini touches the mesh root. It does not necessarily mean there is only one writer. A single MCP server can handle concurrent requests, and the HTTP wrapper may share the same functions.

The plan should specify whether the server is:

- single-threaded,
- async concurrent,
- multi-process,
- protected by an internal dispatcher.

The filesystem primitives are mostly safe, but `update_state` remains last-writer-wins and `scan_and_clear_inbox` has edge cases under concurrent calls from the same agent.

### 7. Medium: `atomic_write_json` path safety has a TOCTOU gap unless the implementation strategy is tighter

The plan requires rejecting symlinks anywhere under the mesh root, but tests that inspect the path before writing do not eliminate a symlink swap between validation and write.

On a local single-user data directory this may be acceptable, but then the trust boundary should be documented. If untrusted local processes can write under the mesh root, the implementation needs fd-relative/openat-style traversal or stricter directory permissions.

### 8. Medium: Message schema is too thin for interoperability

`send_message` only specifies `sender`, `type`, and `body`. For cross-tool use, the message envelope likely needs at least:

- `id`,
- `created_at`,
- `sender`,
- `target`,
- `type`,
- `schema_version`,
- `reply_to` or `correlation_id`.

Without a versioned envelope now, early messages become migration debt.

### 9. Medium: Config/read APIs are missing

The problem statement includes sharing read-only config, but v2 only implements writing `local_rules.json` via bootstrap and says agents must not write it.

There is no planned MCP tool to read config. If agents are remote and have no filesystem access, this is a functional gap.

### 10. Medium-low: Related docs still contain pre-pivot wording that can mislead implementers

`docs/PROBLEM_STATEMENT.md` says logic is "installed independently on each machine," which contradicts the Mac-mini-only runtime described elsewhere. The document later corrects this, but the stale sentence is exactly the kind of phrase someone will copy into an implementation assumption.

### 11. Low: `deploy.sh` verification conflicts with its hard-coded real path

v2 says `deploy.sh` runs exactly:

```bash
uv run agent-mesh-bootstrap --mesh-root /Users/Shared/AgentMesh --agent-ids agent_mac_mini,agent_mbp,agent_ollama_local
```

But verification says to run it against a scratch directory. Either make `deploy.sh` accept a `MESH_ROOT` or argv override for smoke testing, or remove the scratch-dir smoke for the script and test the console entrypoint directly.

## Recommended fixes

1. Add a "v2.1 MCP/API design gate" before implementation proceeds past the local coordinator. It should define tools, JSON schemas, agent identity, authorization assumptions, error mapping, lock handle serialization, and end-to-end tests.

2. Decide inbox delivery semantics explicitly: at-most-once pop, peek-plus-ack, or claim-plus-ack. For agent coordination, avoid delete-before-client-ack unless message loss is acceptable.

3. Add `read_local_rules` / `get_config` to the runtime API if remote agents are expected to consume `local_rules.json`.

4. Clean up `docs/PROBLEM_STATEMENT.md` so no current doc says every machine installs or runs the Python package unless that is still true for clients.

5. Add operational acceptance criteria: launch method, logs, health check, mesh-root permission check, backup/inspection guidance, and manual recovery CLI commands.

## Summary

The filesystem-core plan is much stronger than average. The adversarial weakness is that the MCP pivot is treated as a wrapper, but it is now the security, identity, reliability, and UX boundary. That boundary needs the same level of hostile review the filesystem mechanics already received.
