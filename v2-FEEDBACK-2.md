# Adversarial Review Feedback for Updated `IMPLEMENTATION_PLAN_v2.md`

Review date: 2026-07-23

This is a second adversarial pass after the first `v2-FEEDBACK.md` findings were largely folded into `docs/IMPLEMENTATION_PLAN_v2.md`, `docs/PROBLEM_STATEMENT.md`, and `AGENTS.md`.

## Findings

### 1. High: Claim IDs become path components but are not explicitly validated

The updated plan adds `acknowledge_claims(agent_id, claim_ids)`, and recovery already accepts `claim_ids`. Those claim IDs will be used to address directories under `.processing/<claim_id>/`, which makes them path components just like agent IDs and lock names.

The name-validation invariant still only names "Agent IDs, lock names, and target agent IDs." It should also cover generated and caller-supplied claim IDs. Otherwise an MCP/HTTP caller can pass a malicious or malformed claim ID such as `../x`, an absolute path, mixed case, a Windows-reserved name, or a value that does not match whatever generated claim IDs look like.

Recommendation: define a separate `validate_claim_id` if claim IDs use a different format than human-facing names, or explicitly route claim IDs through `validate_name`. Add tests for `acknowledge_claims` and `recover_processing(claim_ids=...)` rejecting unsafe claim IDs before touching the filesystem.

### 2. High: `acknowledge_claims` is not bound to the claimant or message identity

The new two-phase inbox design fixes delete-before-client-receive loss, but the ack API is very broad: `acknowledge_claims(agent_id, claim_ids)` deletes the named claims for that agent. It does not require the caller to present any claim token, original message ID, or claimant identity from the sidecar.

Given the accepted single-operator tailnet trust model, this is not a security issue in the hostile-client sense. It is still an integrity footgun: a buggy client using the wrong `agent_id` or stale claim IDs can acknowledge and delete another agent's claimed message. Explicit `agent_id` identity makes that easier, not harder.

Recommendation: either document that a claim ID is a bearer delete capability and must be treated as such, or include a random `claim_token` in `.claim.json` and require `{claim_id, claim_token}` on ack. The latter is small and fits the existing lock-token pattern.

### 3. High: Claiming has no batch limit, payload limit, or response-size contract

`claim_inbox_messages` appears to claim every eligible message and return all claimed message bodies. The first feedback called out missing limits; the update fixed acknowledgement semantics but not boundedness.

Failure modes:

- a large inbox can produce an enormous MCP/HTTP response,
- a single huge message body can exceed client/tool limits,
- a caller can unintentionally claim hundreds of messages and then crash before acking, creating a large recovery burden,
- a slow client can hold many messages in `.processing/` while processing serially.

Recommendation: add `max_messages` with a conservative default, and either `max_bytes` or a documented message-size limit enforced by `send_message` and `claim_inbox_messages`. Test that only the selected batch is claimed and that oversized messages are reported/quarantined/fail closed according to an explicit rule.

### 4. Medium-high: The claim sidecar write failure path is still underspecified

The claim sequence is `mkdir` claim dir, rename message into it, then write `.claim.json`. A crash after rename but before sidecar is covered by recovery as "message-without-sidecar." But an in-process exception while writing the sidecar is not specified as clearly as lock token write failure is.

Questions an implementer could answer inconsistently:

- Should `claim_inbox_messages` raise, return a partial batch, or report the failed claim?
- Should it attempt to requeue the message if sidecar writing fails?
- If it leaves the message-without-sidecar orphan for recovery, should the rest of the scan continue?
- If the sidecar write produces malformed/truncated JSON, is that possible under the same atomic-write rules, or is `.claim.json` written directly?

Recommendation: mirror the lock-token clarity. Specify that `.claim.json` is also written atomically, and define the exact behavior if sidecar writing raises after the message rename. Add a test that monkeypatches the sidecar write to fail after the rename.

### 5. Medium-high: Periodic recovery is recommended, but there is no operator command for it

The MCP section now says operators should run `recover_processing(..., action="requeue")` periodically once agents run unattended. But `recover_processing` is explicitly not exposed as an MCP tool, and the tooling section only defines `agent-mesh-bootstrap`.

That leaves no planned CLI entrypoint for the most important maintenance operation in the two-phase ack design. "Run a Python function directly on the Mac mini" is too vague for something expected to run manually or from cron/launchd.

Recommendation: add an admin console script such as `agent-mesh-recover-processing`, with arguments for `--mesh-root`, `--agent-id`, `--older-than-seconds`, `--claim-id`, `--action`, and `--dry-run`. Keep it admin-only and local-only; it does not need to be an MCP tool.

### 6. Medium: `health_check()` counts are not actionable enough for manual recovery

`health_check()` returns `lock_count` and `processing_claim_count`. Counts tell the operator that something exists, but not which agent, which claim IDs, how old they are, or which locks need inspection.

That is weak visibility for a design that deliberately relies on manual recovery and has no stale-lock breaking. It still forces SSH/filesystem inspection for the next step.

Recommendation: either expand `health_check()` to include per-agent counts plus oldest claim age and lock names, or add separate read-only admin/status functions such as `list_processing_claims` and `list_locks`. Avoid exposing message bodies or tokens in health output.

### 7. Medium: The plan says MCP framework choice is "purely mechanical," but it can affect behavior

The update correctly fixes the API surface, but it now swings too far by calling the remaining MCP work "purely mechanical." The framework/transport choice can affect:

- whether tools are local stdio or remote HTTP/SSE/WebSocket,
- whether binding to a Tailscale interface is actually supported by the server mode,
- request timeout behavior for long polling or large inbox responses,
- cancellation behavior during a claim call,
- error serialization and whether partial results are possible,
- whether the HTTP wrapper can really share the exact same dispatch layer.

Recommendation: keep the current API decisions, but add a short MCP framework selection gate before implementation of `mcp_server.py`. That gate should verify binding mode, timeout/cancellation behavior, error mapping, and whether the chosen framework supports the intended Claude Code/Codex registration path.

### 8. Medium: `send_message` lacks an explicit message-size and JSON-shape policy

The envelope is now versioned, which is good. But `body` remains arbitrary JSON with no size, object/array/scalar policy, or reserved fields. Since messages are returned through MCP/HTTP tool responses, unbounded payloads are a practical reliability issue even in a trusted personal mesh.

Recommendation: set a v1 max serialized message size and decide whether `body` must be a JSON object. Reject oversize/nonconforming bodies before writing. Add tests for clean failure leaving no temp/message file.

### 9. Medium-low: Current docs are out of sync on the previous feedback file name/location

The updated plan references `v2-FEEDBACK.md`, but that file no longer exists at the repo root; it appears to have been archived as `docs/archive/PLAN_FEEDBACK-v2.md`. `AGENTS.md` uses the archived name. This is small, but these docs are meant to guide cold-start agents, and broken filenames create retrieval misses.

Recommendation: update `docs/IMPLEMENTATION_PLAN_v2.md` to reference `docs/archive/PLAN_FEEDBACK-v2.md` or restore a root-level pointer file.

### 10. Medium-low: `AGENTS.md` key invariants still describe the old one-step inbox API

`AGENTS.md`'s "Key invariants" section still describes inbox processing as scan-and-clear and does not include the new claim/ack split, versioned envelope, `read_local_rules`, or the explicit MCP identity/trust model until later sections. A cold-start agent may read the invariant list and implement the old API shape before reaching the later correction.

Recommendation: update the invariant bullets in `AGENTS.md` to match v2's current claim/ack API and config read behavior, not only the later "Coordinator API shape" section.

### 11. Low: The root documentation layout conflicts with creating new root feedback files

`AGENTS.md` says the root should contain only `CLAUDE.md` and `AGENTS.md`, while the workflow still creates root-level feedback files like this one. The prior feedback was moved to `docs/archive/PLAN_FEEDBACK-v2.md`.

Recommendation: decide the convention. Either feedback files should be created directly in `docs/archive/` under the `PLAN_FEEDBACK-v2-N.md` pattern, or root-level feedback files are allowed as temporary review artifacts until absorbed.

## Recommended fixes

1. Add claim ID validation and tests anywhere claim IDs are accepted from callers.

2. Decide whether claim IDs are bearer delete capabilities. Prefer adding `claim_token` to the sidecar and ack request, matching the lock-token pattern.

3. Add `max_messages` and message-size limits to `claim_inbox_messages` / `send_message`.

4. Specify and test sidecar write failure after message rename.

5. Add a local admin CLI for `recover_processing` before relying on periodic recovery.

6. Make health/status output actionable without exposing payloads or tokens.

7. Add an MCP framework selection gate instead of treating that layer as purely mechanical.

8. Fix doc drift around `v2-FEEDBACK.md` vs `docs/archive/PLAN_FEEDBACK-v2.md`, and bring `AGENTS.md`'s invariant bullets in sync with the updated v2 plan.

## Summary

The update substantially improves the plan: the MCP boundary is now acknowledged, claim/ack avoids silent message loss, config reads are planned, and the trust model is explicit. The remaining risk is that the newly-added boundary semantics are not yet as rigorously specified as the older filesystem primitives. The next tightening pass should focus on caller-supplied claim IDs, bounded inbox delivery, actionable admin recovery, and keeping the root guidance synchronized with the plan.
