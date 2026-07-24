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
  (locks, atomic writes, state, messaging, `health_check`), `inbox.py`
  (claim, acknowledge, recovery), `rules_template.py` (write **and**
  read), `bootstrap.py`, `mcp_server.py` (FastMCP 2.x tool layer over
  streamable HTTP — see "Decision (2026-07-23)" in "MCP/HTTP API design"
  below for the framework choice). The tool list, request/response
  shapes, caller-identity model, lock-handle serialization, and inbox
  delivery/acknowledgement semantics were all decided ahead of the build
  (see "MCP/HTTP API design"), in response to
  `docs/archive/PLAN_FEEDBACK-v2.md`'s finding that treating the MCP layer
  as a thin wrapper understated it: it's the mesh's actual
  security/identity/reliability boundary, and that needed a design
  decision, not a placeholder.
- **Named in the repo layout but not yet built:** the Ollama HTTP wrapper
  (`TASK-9`) — a thin route set over the same functions `mcp_server.py`
  already wraps, sharing its dispatch/error-mapping code rather than
  duplicating it.
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
- **Claim IDs are validated before they become path components too** —
  they address `.processing/<claim_id>/` directories exactly like agent
  IDs and lock names address theirs, and once `acknowledge_claims` and
  `recover_processing(claim_ids=...)` accept them from a caller (an
  MCP/HTTP client, not just internally-generated), the same
  path-traversal risk `validate_name` closes for agent IDs applies here.
  Claim IDs are never human-authored, though, so they get their own
  narrower `validate_claim_id` rather than reusing `validate_name`'s
  human-facing rules (no lowercase-policy debate, no Windows-reserved-name
  concern): a claim ID must match exactly the format the generator
  produces (e.g. a fixed-length lowercase-hex `uuid4().hex`) — anything
  else (separators, `..`, wrong length/charset) is rejected with
  `ValueError` before any path is touched, in both `acknowledge_claims`
  and `recover_processing(claim_ids=...)`.
- **Inbox messages are claimed before processing**, not read-then-deleted,
  and **claiming and deleting are two separate operations**, not one
  atomic pop. `claim_inbox_messages(agent_id, max_messages=50)` does the
  atomic `mkdir(.processing/<claim_id>/)` (retried with a new ID on a rare
  claim-ID collision, bounded retry count) followed by renaming the
  message into it — **the rename, not the `mkdir`, enforces exclusivity**,
  since only one renamer can win against the shared source path — then a
  `.claim.json` sidecar (`claimant_agent_id`, `claimed_at`, `claim_token`)
  is written **atomically, using the same `atomic_write_json` primitive as
  everything else** (not a bespoke write path), and returns the claimed
  messages (still on disk, not yet deleted) together with their claim IDs
  and tokens.

  **`max_messages` bounds attempted claims, not just successfully-returned
  ones** — this distinction matters because a sidecar-write failure (see
  below) removes a message from the inbox without returning it, and
  bounding only successful returns would let a run of failures move an
  unbounded number of messages out of the inbox while chasing 50
  successes. Concretely: `claim_inbox_messages` looks at at most
  `max_messages` eligible source messages in one call, full stop — some
  subset of those may fail their sidecar write and become orphans instead
  of being returned, but the total moved out of the inbox in one call
  is still bounded by `max_messages`. A separate `max_attempts`/
  `max_failures` knob was considered and rejected as unnecessary
  additional configuration surface: bounding the one number that already
  exists is enough to close the failure mode. **`max_messages` itself is
  validated as caller input**: it must be an integer with
  `1 <= max_messages <= MAX_CLAIM_BATCH_SIZE` (a module-level constant,
  `50` — the same as the default, since nothing in scope needs a caller
  to ask for more); zero, negative, non-integer, or over-the-cap values
  raise `ValueError` before the inbox is touched at all. Each stored
  message body is capped at a documented max serialized size (see the
  envelope bullet below); `claim_inbox_messages` never has to handle an
  oversized message, because `send_message` already refused to write one.

  `acknowledge_claims(agent_id, [{claim_id, claim_token}, ...])` is a
  separate call that deletes the message + sidecar + claim dir for each
  given `(claim_id, claim_token)` pair, and reports — per item, not as a
  single all-or-nothing result — one of: `acknowledged`; `not-found`
  (claim ID doesn't exist at all: already acknowledged, or never valid);
  `token-mismatch` (a *complete* claim exists — valid sidecar, readable
  token — but the given token doesn't match it); or `unacknowledgeable`
  (the claim directory exists but isn't in a state a token comparison can
  even be performed against — one of the three orphan shapes
  `recover_processing` already understands: empty dir, message-without-
  sidecar, or message-with-malformed-sidecar — reported with which shape,
  reusing the same shape vocabulary as recovery rather than inventing
  three new status strings). **`unacknowledgeable` claims are left
  completely untouched by `acknowledge_claims`** — it never deletes
  anything it can't verify a token against; the caller's only path forward
  for those is the operator-invoked `recover_processing`, same as any
  other orphan. **A caller-supplied `claim_token` is validated as input,
  not just compared**: it must be a non-empty string, or `acknowledge_claims`
  raises `ValueError` before reading/deleting anything — a well-formed but
  wrong string is a normal `token-mismatch`/`not-found` result, not an
  error. Generated `claim_token`s are `secrets.token_hex(16)` (32
  lowercase hex characters) — high-entropy and opaque, matching the
  charset (though not the purpose) of generated claim IDs for one
  consistent "these are machine-generated identifiers, not human input"
  family. **The token is an integrity check, not a security boundary** —
  nothing here defends against a hostile caller (see "MCP/HTTP API
  design" below for why that's out of scope); its job is to stop a
  *buggy* client — wrong cached claim ID, stale list, copy-paste error —
  from silently deleting a claim it never actually made, which plain
  `agent_id` + `claim_id` wouldn't have caught since `agent_id` is already
  an unverified, caller-asserted parameter. A token mismatch never deletes
  anything; it's reported so the caller (or a human reading logs) notices
  the bug.

  **This claim/acknowledge split exists because a network caller (the MCP
  server) can succeed in claiming a message server-side and then lose the
  connection before the client receives or processes it** — if
  claim-and-delete were one step, that message would be silently lost.
  With the split, an un-acknowledged claim just sits in
  `.processing/<claim_id>/` exactly like any other crash-orphaned claim,
  and is recovered the same way (see `recover_processing` below) — no new
  ack-timeout machinery needed, this reuses the recovery path the local
  claim design already required. `scan_and_clear_inbox(agent_id)` remains
  as a convenience wrapper — `claim_inbox_messages` immediately followed by
  `acknowledge_claims` on everything it claimed (using the tokens it just
  received, not re-derived) — for in-process callers that don't need the
  two-phase split (tests, `bootstrap`-adjacent tooling, a simple local
  polling script run directly on the Mac mini).

  **A crash between the message rename and the sidecar write is a named,
  tested case, not an unspecified one**: if writing `.claim.json` raises
  (disk error, process killed mid-write), `claim_inbox_messages` does
  *not* attempt to move the message back to the inbox — a further
  filesystem operation at exactly the moment something already just
  failed would only compound the failure. Instead it leaves that message
  in the message-without-sidecar orphan shape (already one of the four
  states recovery understands), excludes it from the batch returned to
  the caller, reports it distinctly in the result (not silently dropped),
  counts against that call's `max_messages` bound (see above — this is
  exactly the failure mode the attempts-not-successes bound exists for),
  and **continues claiming the rest of the eligible messages** rather
  than aborting the whole call — one bad claim doesn't block delivery of
  everything else.

  Malformed messages are quarantined into `inbox/.invalid/`, never left in
  place for endless rediscovery; other ignored files (stray
  `.tmp_*`/hidden) are reported in `InboxScanResult.ignored`, not silently
  dropped. A crashed/killed claimant (or an MCP client that never
  acknowledges) leaves its claim in one of four identifiable states — empty
  dir, message-without-sidecar, message-with-malformed-sidecar, or a
  complete claim — recoverable only via an explicit, operator-invoked
  `recover_processing(older_than_seconds | claim_ids, action)` call, never
  automatically. An *empty* claim dir is **not** a special case removed
  unconditionally — it's also the normal transient state of a live
  scanner mid-claim, so it goes through the exact same age/selection
  rules as every other shape; recovery should be run while the target
  agent is stopped. When an empty claim dir is selected and a real action
  is requested, there is no message to move, so recovery means removing
  that now-useless empty claim directory. The age threshold is a heuristic,
  not a correctness guarantee (cross-machine clock skew) — `claim_ids` is
  the clock-skew-proof override. **A successful `requeue`/`quarantine` also cleans up after
  itself**: once the message file has been moved, `recover_processing`
  removes the `.claim.json` sidecar (if present — it contains a
  `claim_token`, so leaving it behind after the claim it belongs to no
  longer exists is stale, misleading metadata, not just clutter) and then
  the now-empty claim directory. If that cleanup step itself fails after
  the message was already safely moved, that's reported as a partial
  recovery in the result (the important half — the message is safe —
  already succeeded), never silently swallowed and never a reason to
  recursively delete unexpected extra contents in the claim dir (same
  "never force-delete the unknown" rule as lock release). `requeue`/
  `quarantine` still fail closed (raise) on a destination filename
  collision for the message itself, before any of this cleanup happens.
- **The stored message envelope is versioned, self-describing, and
  bounded**, not just `(sender, type, body)`: every message file's JSON is
  `{schema_version, id, created_at, sender, target_agent_id, type, body}`.
  `id`/`created_at` make messages independently identifiable outside the
  filename (useful once a message has been `requeue`d and its filename
  context is gone); `target_agent_id` is redundant with which inbox the
  file lives in but cheap to include and useful for a human inspecting a
  requeued/quarantined message in isolation. **`body` must be a JSON
  object** (not a bare scalar or array) — gives every message a stable
  place to add fields later without a shape migration. **`type` (the
  message type) is validated too, lightly** — it's protocol surface other
  agents will eventually dispatch on, not just a free-text field: a
  non-empty string, capped at a conservative length (64 chars), matching
  a portable token pattern (lowercase letters/digits plus `.`, `-`, `_` —
  e.g. `heartbeat`, `task.assigned`); anything else raises `ValueError`
  before writing. This reuses the *idea* behind `validate_name` (fail
  loud on malformed protocol input, don't silently coerce) without
  reusing the function itself — `type` never becomes a path component, so
  it doesn't need `validate_name`'s path-safety rules, just its own
  narrower shape check in `coordinator.py`, not `names.py`.

  **The serialized envelope has a documented max size — 256 KiB in v1 —
  measured precisely, not approximately**: the size checked is
  `len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))`,
  i.e. exactly the bytes `atomic_write_json` is about to write (compact
  separators, no added whitespace, no trailing newline, `ensure_ascii=False`
  so non-ASCII content is measured by its actual UTF-8 byte length rather
  than inflated by `\uXXXX`-escaping). This is the one serialization
  policy used for every size check in v1 — not a separate rule per
  caller. `send_message` rejects anything over that limit or with a
  non-object `body` before writing (`ValueError`, no temp/message file
  left), so oversized payloads are never a problem `claim_inbox_messages`
  or an MCP/HTTP response has to deal with downstream. Boundary tests
  cover exactly-at-the-limit and one-byte-over, plus a non-ASCII payload
  to confirm the byte count (not the character count) is what's enforced.
  Deliberately **not** included in v1: `reply_to`/`correlation_id` —
  nothing in scope needs request/response threading between messages
  yet; add it when a real caller needs it, not speculatively.
- **Message ordering is best-effort filename order only** — no
  cross-machine causal or wall-clock guarantee. No per-sender sequence
  numbers in v1, since nothing in scope needs strict ordering yet.
- **Filesystem watchers are a v2+ concern.** v1 ships polling-only
  (`scan_and_clear_inbox`); prefer watchers (e.g. `watchdog`) over
  tighter polling loops once there's an actual latency need.
- **`config/local_rules.json` is read-only for agents** — written only by
  the human operator (via `bootstrap_mesh`/`deploy.sh`), never by any
  agent process at runtime. **Read access is a real, planned function**,
  not an accidental gap: `read_local_rules(mesh_root)` (in
  `rules_template.py`, alongside the existing writer) parses and returns
  the current file, raising `FileNotFoundError` if the mesh hasn't been
  bootstrapped yet — this is what remote agents need, since they have no
  filesystem access to peek at the config themselves once they're only
  reaching the mesh through MCP/HTTP. The same single-writer,
  operator-only-write / anyone-can-read rule applies to `file_trees.json`
  whenever it's eventually built (not in this plan's scope).
- **The mesh root has exactly one writer process, the MCP server on the
  Mac mini — but that process itself may field concurrent requests.**
  "No concurrent writers" describes the network/cross-machine picture (no
  other machine ever touches the mesh root), not intra-process
  concurrency: the MCP server can and will dispatch multiple in-flight
  tool calls against the same `AgentMeshCoordinator` instance, whether
  it's built single-threaded, threaded, or async. That's exactly what the
  lock/atomic-write primitives above are already designed and tested for
  (the `ThreadPoolExecutor` exactly-one-winner lock test in particular)
  — the server should reuse one long-lived coordinator instance per
  mesh root rather than one per request, and no *additional* concurrency
  mechanism is needed beyond what's already specified. `update_state`
  being last-writer-wins is intentional, not a gap: it's a per-agent
  heartbeat file that only that agent ever writes, so "last write wins"
  is the correct behavior for two heartbeats from the same agent racing,
  not a defect to fix.
- **Trust boundary: the Mac mini's local disk is a single-operator,
  single-user machine — this design does not defend against a hostile
  local process.** `atomic_write_json`'s symlink checks close off
  accidental/incidental symlinks (e.g. a stray symlink left by tooling)
  and mesh-root escapes; they are **not** hardened against a
  time-of-check-to-time-of-use race where an adversarial local process
  swaps a path component between validation and write (that would need
  `openat`-style fd-relative traversal, real added complexity). That's an
  accepted, explicit scope boundary given the trust model — no untrusted
  process runs on the Mac mini with write access to the mesh root or its
  parent directories — not a silently-unexamined gap. Revisit if that
  trust model ever changes (e.g. the mesh root becomes reachable by code
  Jacob doesn't control).

## MCP/HTTP API design

`docs/archive/PLAN_FEEDBACK-v2.md` correctly pushed back on treating the
MCP server as a thin, deferrable wrapper: once other machines never touch
the mesh root directly, the MCP/HTTP layer *is* the mesh's identity,
delivery, and reliability boundary, not an afterthought. This section
makes the decisions that boundary needs. It does not pick an MCP server
framework or write dispatch code — that's real plumbing work deferred
until the modules above exist and pass their own tests — but every
question about *behavior at the boundary* is answered here, not left
open.

**Trust model (why this is deliberately lighter than a multi-tenant
design):** every caller is Jacob's own tooling (Claude Code, Codex, local
Ollama-backed scripts) on Jacob's own machines, reaching the Mac mini over
his own Tailscale tailnet. There is exactly one human operator and no
adversarial or third-party clients. This matters directly for the
decisions below — building session auth, request signing, or
anti-impersonation defenses would be solving a problem this project
doesn't have. **The stated boundary is the tailnet itself**: the MCP
server binds only to the Mac mini's Tailscale interface, so reachability
already requires being a device on Jacob's tailnet. If that trust model
ever changes (a shared/multi-user tailnet, third-party tooling), these
decisions need to be revisited — that's an explicit note, not a silent
gap.

- **Caller identity is an explicit parameter, not inferred from the
  transport.** Every MCP tool call that needs an agent identity takes
  `agent_id` as an explicit argument (e.g. `update_state(agent_id=...,
  ...)`, `send_message(agent_id=..., target_agent_id=..., ...)`) — it is
  *not* derived from a session, connection, or client certificate. A
  caller can technically claim to be any `agent_id` it wants (there is no
  anti-spoofing layer); this is accepted given the trust model above, the
  same way a caller could already do that against the local Python API.
  This is a real design decision, not an oversight: if the trust model
  changes, the fix is per-tool-call identity verification against
  something the MCP transport actually authenticates (e.g. a per-machine
  token issued at registration time) — not built now because nothing in
  scope needs it.
- **Lock handles serialize to plain data, with no server-side session
  registry.** A `LockHandle` crossing the MCP boundary becomes
  `{"lock_name": ..., "token": ...}` — the client holds and re-submits it
  to `release_lock`. There is no additional server-side table mapping
  handles to callers or connections; a client that loses its handle (or
  the MCP server restarts) leaves an unreleased lock exactly as if the
  local Python caller had done the same thing — the existing "no
  stale-lock breaking, manual operator cleanup" invariant already covers
  this, so no new mechanism is needed. Locks, claims, and tokens all live
  on disk, so an MCP server restart loses no state — it just stops being
  able to release handles it never received again, same as today.
- **Runtime-facing coordinator methods exposed as MCP tools:**
  `acquire_lock`, `release_lock`, `update_state`, `send_message`,
  `claim_inbox_messages`, `acknowledge_claims`, `read_local_rules`,
  `health_check` (new — see "Operational readiness" below).
  `atomic_write_json` is an internal primitive, never exposed directly.
  `recover_processing` and `bootstrap_mesh` stay operator/admin-only, run
  directly on the Mac mini — never exposed as tools, consistent with their
  existing "not part of the runtime API" status.
- **Inbox delivery is claim-then-acknowledge over MCP, not
  claim-then-delete in one call** — see the "Inbox messages are claimed
  before processing" design invariant above for the mechanics, the
  `claim_token` integrity check, and the `max_messages`/size bounds.
  Concretely for a remote caller: call `claim_inbox_messages`, process the
  returned messages, then call `acknowledge_claims` with their
  `(claim_id, claim_token)` pairs. A dropped connection between those two
  calls leaves the claim recoverable via `recover_processing`, not
  silently lost. Operators should run
  `recover_processing(older_than_seconds=<some threshold>,
  action="requeue")` periodically once agents are actually running
  unattended, so an un-acknowledged claim (crashed client, dropped
  connection) eventually gets redelivered rather than sitting forever —
  via the admin CLI below, still an explicit, human/cron-invoked action,
  never automatic inside the server itself.
- **Error mapping is "let it raise, map at the boundary."** Coordinator/
  inbox functions keep raising the specific Python exceptions already
  specified in the TDD cycles below (`ValueError`, `FileNotFoundError`,
  `NotADirectoryError`, etc.); `mcp_server.py`'s job is only to catch
  those at the tool-call boundary and map them to whatever error shape
  the chosen MCP framework expects, one-to-one, without inventing a new
  parallel error taxonomy. This is a mapping-layer requirement to design
  in `mcp_server.py`'s own build, not a reason to change the exceptions
  already specified.
- **MCP framework selection gate — a deliberate correction to this
  document's own earlier framing.** An earlier draft of this section
  called the remaining `mcp_server.py` work "purely mechanical"; that
  overstated it, and the framework choice is now called out as a real
  decision with behavioral consequences, not a fungible implementation
  detail. Before writing `mcp_server.py`, whichever MCP
  library/SDK is chosen must be checked against: (1) can it bind to a
  specific interface (the Mac mini's Tailscale IP), not just localhost or
  all-interfaces; (2) what are its default timeout and cancellation
  semantics for a long-running tool call (relevant to `claim_inbox_messages`
  against a large or slow-to-scan inbox); (3) does it support partial/
  streamed results, or is every tool call all-or-nothing; (4) how does it
  serialize/report errors raised by tool code, so the "let it raise, map
  at the boundary" rule above has somewhere concrete to plug into; (5)
  does it actually support the registration path Claude Code and Codex
  expect. This is a short compatibility check against the chosen
  framework's docs before committing, not a research project — but it's a
  real gate, not a formality.

**Decision (2026-07-23): FastMCP 2.x (the `fastmcp` PyPI package,
jlowin/PrefectHQ), over streamable HTTP.** Checked against the gate above:

1. **Binding**: `mcp.run(transport="streamable-http", host=..., port=...)`
   supports binding to a specific interface — including a previously-fixed
   issue where `host` wasn't being passed through to the SDK's own
   DNS-rebinding-protection logic, only to the underlying ASGI server.
   The fact that issue existed and got fixed is itself a good sign: someone
   else already needed exactly our scenario (a real bound interface, not a
   proxy-fronted localhost).
2. **Timeout/cancellation**: client-side `timeout=` on tool calls and
   server-side `ctx.report_progress()` are both supported over
   streamable-http. One real, documented gap: a client timing out mid-call
   can raise `ClosedResourceError` that crashes the server process. This is
   mitigated by design rather than avoided — `TASK-10`'s `launchd`
   `KeepAlive` restart plus the fact that all coordinator state lives on
   disk (a crash-restart loses no lock/claim state, per "Operational
   readiness" below) makes this an acceptable-but-real risk, not a
   blocker. `mcp_server.py`'s own build should still wrap tool dispatch
   defensively rather than relying solely on the restart safety net.
3. **Partial/streamed results**: supported via progress callbacks; not
   needed for anything in our tool list, since every tool is already
   bounded (`max_messages=50`, 256 KiB/message) — a non-issue given the
   API surface already decided above.
4. **Error serialization**: FastMCP 2.x distinguishes a plain raised
   exception (caught, masked to a generic client-facing message —
   `mask_error_details=True` by default, good for not leaking internals)
   from `ToolError` (message passed through verbatim). This maps directly
   onto the "let it raise, map at the boundary" rule: catch our specific
   exceptions (`ValueError`, `FileNotFoundError`, etc.) at the tool
   boundary and re-raise as `ToolError(str(exc))`, so callers get the
   actual reason rather than a masked generic message.
5. **Registration path**: confirmed for both clients — `claude mcp add
   --transport http <name> <url>` and `codex mcp add --url <url>`, both
   using streamable HTTP as the current recommended remote transport
   (SSE is deprecated on the Claude Code side, and stdio is the wrong
   model here anyway — it means a client-spawned local process, not one
   shared server reached by multiple remote machines).

**Why FastMCP 2.x over the official SDK's built-in `FastMCP`**: both
pass the gate, but the official `modelcontextprotocol/python-sdk` is
mid-major-rework (v2 targeted essentially now, alongside a new spec
release), meaning adopting it today means adopting a package about to
churn. FastMCP 2.x is the currently-stable, more feature-complete option
(clearer error-masking story, more deployment documentation), and is
itself descended from the same code the official SDK's basic `FastMCP`
class originated from.

## Operational readiness

A persistent daemon needs an operational story, not just correct logic.
Scoped for a single-operator, 2–3-machine personal mesh — not a full SRE
runbook:

- **Process supervision**: a `launchd` plist on the Mac mini
  (`RunAtLoad` + `KeepAlive`) restarts the MCP server on crash. Since all
  lock/claim state lives on disk, a restart loses no coordination state —
  it only drops in-memory client handles, which is the same accepted
  "manual cleanup" limitation as any other crash (see "Lock handles
  serialize to plain data" above).
- **Logging**: stdout/stderr redirected to a log file (e.g.
  `~/Library/Logs/agent-mesh-core/mcp_server.log` on the Mac mini). No
  rotation infrastructure in v1 — accepted simplicity at this scale, not
  an oversight; revisit if log volume ever becomes a real problem.
- **Startup validation**: before accepting any tool calls, the server
  verifies the configured mesh root exists, is a directory, and is
  writable, and fails fast with a clear error and non-zero exit if not —
  rather than accepting requests against a broken mesh root and failing
  confusingly on the first real write.
- **`health_check()`**: a read-only MCP tool (also exposed over the HTTP
  wrapper) returning enough to decide whether recovery is needed without
  SSHing in and inspecting the filesystem by hand — a bare count wasn't
  enough for that. **Locks are reported as their own top-level field, not
  nested under agents**: `locks/` is a global directory with no owning
  agent recorded anywhere (a lock's `owner.token` proves nothing about
  *which agent* acquired it, only that a specific acquire call did), so
  nesting `lock_names` under `agents` would have meant either inventing
  ownership data the design doesn't track or duplicating every lock name
  under every agent — both wrong. The corrected shape is
  `{status, mesh_root, agents: [{agent_id, processing_claims: [{claim_id,
  shape, age_seconds}]}], locks: [{lock_name, shape, age_seconds}]}`.
  Processing-claim `shape` is one of the four `recover_processing` already
  understands (empty / no-sidecar / malformed-sidecar / complete); lock
  `shape` is one of two — `token-present` (normal, possibly still held) or
  `token-missing` (the accepted hard-crash-between-`mkdir`-and-token-write
  limitation, needing manual cleanup) — reflecting that locks don't have
  the same four-shape lifecycle claims do. **Never includes message
  bodies, claim tokens, or lock owner tokens** — enough to decide
  *whether* and *what* to recover, not a substitute for
  `recover_processing`'s own dry-run report, which stays the source of
  truth for the actual recovery decision. This is visibility, not
  automatic remediation — the fix is still the explicit
  `recover_processing` call below, deliberately. (An earlier draft
  considered adding separate `list_processing_claims`/`list_locks` tools
  instead; enriching `health_check()`'s own output was chosen as the
  smaller addition — revisit only if a real caller needs something
  `health_check()` doesn't already surface.)
- **Admin CLI for `recover_processing`**: `recover_processing` is
  operator-only and deliberately not an MCP tool, but "run a Python
  function directly on the Mac mini" isn't a real entrypoint for the
  maintenance operation the claim/acknowledge design now depends on.
  `agent-mesh-recover-processing` (console script, local-only, admin-only
  — same tier as `agent-mesh-bootstrap`) wraps it with
  `--mesh-root`, `--agent-id`, `--older-than-seconds`, `--claim-id`
  (repeatable), `--action` (`report`/`requeue`/`quarantine`), and
  `--dry-run` (forces `action=None` regardless of `--action`, for safe
  inspection). This is what a human runs by hand or from a `launchd`/cron
  job for the periodic-requeue recommendation above — it is a thin
  argument-parsing wrapper around the already-tested `recover_processing`,
  not new coordination logic.

## Repo layout

```
agent-mesh-core/
├── pyproject.toml
├── .gitignore
├── deploy.sh                        # thin, local-only: invoke `agent-mesh-bootstrap` against the local mesh root
├── src/agent_mesh_core/
│   ├── __init__.py
│   ├── names.py             # validate_name(): strict portable regex + Windows-reserved-name/lowercase checks; validate_claim_id(): fixed-format generated-ID check
│   ├── coordinator.py       # AgentMeshCoordinator: token-checked LockHandle locks, mesh-root-confined atomic_write_json (fsync'd), update_state, send_message (size/shape-bounded envelope)
│   ├── inbox.py             # claim_inbox_messages / acknowledge_claims (claim_token-checked) + InboxScanResult (claim into .processing/<claim_id>/ dirs) + scan_and_clear_inbox (local convenience wrapper) + recover_processing() + recover_main() CLI entrypoint
│   ├── rules_template.py    # local_rules.json generator/writer + read_local_rules() reader
│   ├── bootstrap.py         # bootstrap_mesh(): wires coordinator init + rules template + default agent dirs
│   ├── mcp_server.py        # build_server(mesh_root) -> FastMCP: wraps acquire_lock/release_lock/update_state/send_message/claim_inbox_messages/acknowledge_claims/read_local_rules/health_check as FastMCP 2.x tools over streamable HTTP; CoordinatorRegistry caches one AgentMeshCoordinator per agent_id; _map_tool_errors re-raises ValueError/FileNotFoundError/NotADirectoryError/FileExistsError as ToolError
│   └── templates/
│       └── local_rules.template.json
└── tests/
    ├── conftest.py
    ├── test_names.py
    ├── test_coordinator_init.py
    ├── test_coordinator_locks.py
    ├── test_coordinator_atomic_write.py
    ├── test_coordinator_health.py
    ├── test_coordinator_state.py
    ├── test_coordinator_send_message.py
    ├── test_inbox_scan.py
    ├── test_inbox_recovery.py
    ├── test_inbox_recover_cli.py
    ├── test_rules_template.py
    ├── test_bootstrap.py
    ├── test_bootstrap_integration.py
    └── test_mcp_server.py
```

`health_check()` lives on `MeshJsonWriter` (the identity-free base class), not
`AgentMeshCoordinator`, precisely so `mcp_server.py`'s `health_check` tool
can call it without constructing a synthetic per-agent identity as a side
effect — it never touched `self.agent_id` in the first place, so the move
changes nothing about `AgentMeshCoordinator.health_check()`'s existing,
tested behavior (inherited unchanged).

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
- `validate_claim_id` — accepts exactly the generated claim-ID format
  (e.g. `uuid4().hex`), rejects anything else (separators, `..`, wrong
  length/charset) before `acknowledge_claims` or
  `recover_processing(claim_ids=...)` touch any path
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
- `send_message` payload shape (`schema_version`, `id`, `created_at`,
  `sender`, `target_agent_id`, `type`, `body`), missing-inbox error,
  target-is-not-a-directory error, message-id uniqueness under identical
  timestamps, rejecting a non-object `body`, an invalid `type`, or an
  envelope over the documented size limit (measured against the exact
  serialization bytes) before writing anything
- Inbox claim/acknowledge — `claim_inbox_messages` validates `max_messages`
  (integer, `1..MAX_CLAIM_BATCH_SIZE`) before touching the inbox; does the
  atomic claim via `mkdir` (with bounded retry on claim-ID collision) +
  rename into `.processing/<claim_id>/` + an atomically-written sidecar
  (including a `claim_token`), returning claimed messages and their
  tokens without deleting them; `max_messages` bounds *attempted* claims
  (successful or orphaned), not just successful returns, so repeated
  sidecar-write failures can't move an unbounded number of messages out
  of the inbox in one call; continues past a single claim's sidecar-write
  failure rather than aborting the whole batch; `acknowledge_claims`
  validates each `claim_id` (via `validate_claim_id`) and `claim_token`
  (non-empty string) before touching anything, deletes a given set of
  `(claim_id, claim_token)` pairs, and reports — per item — acknowledged /
  not-found / token-mismatch / unacknowledgeable (an orphan shape with no
  valid token to check), never silently ignoring or force-deleting on a
  mismatch or an unacknowledgeable claim; `scan_and_clear_inbox` is a thin
  wrapper composing the two; malformed JSON quarantined (not left in
  place), tolerating concurrent-claim races and all four orphan shapes,
  documented best-effort-only ordering, ignored files reported not
  dropped
- `recover_processing` — validates any caller-supplied `claim_ids` via
  `validate_claim_id` before touching the filesystem; cleans up the
  sidecar and now-empty claim dir after a successful requeue/quarantine
  move, reporting (not raising past) a failure in that cleanup step;
  reports/requeues/
  quarantines claims (uniformly across all orphan shapes, including empty
  claim dirs) by age threshold (heuristic only) or by explicit `claim_ids`
  override, failing closed on a requeue/quarantine destination collision;
  never invoked automatically
- `local_rules.json` generation and reading — default content, deep-merge
  of overrides, refuse-to-overwrite without `force`; `read_local_rules`
  parses and returns the current file, raising `FileNotFoundError` before
  bootstrap has run
- `bootstrap_mesh` orchestration — which agent dirs get created (with
  duplicate-after-normalization rejection), call order (coordinator init
  before rules template), and that it surfaces (not swallows) a
  refuse-to-overwrite error from the rules template step
- `recover_main()` CLI argument parsing — maps `--mesh-root`,
  `--agent-id`, `--older-than-seconds`, repeated `--claim-id`, `--action`,
  and `--dry-run` onto `recover_processing`'s actual parameters
  (`--dry-run` forcing `action=None` regardless of `--action`); thin, but
  the flag-to-parameter mapping is real logic worth one direct test, not
  zero

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
- **Inbox claim concurrency strategy**: force one generated claim-ID
  collision to prove bounded retry, and run a real `ThreadPoolExecutor`
  race where two claimers target the same single source message, asserting
  exactly one claimant wins the `os.rename` and the losing claim dir is
  cleaned up.

## TDD cycle sequence

### `names.py`
1. `test_names.py` — accepts typical IDs (`agent_mac_mini`, `agent-mbp-2`); rejects empty string, path separators (`/`, `\`), `..`, absolute paths, leading dot/dash, length over 64, non-ASCII/whitespace, uppercase characters (lowercase-only policy), and Windows-reserved device names (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`, case-insensitive); `validate_name` raises `ValueError` with the offending value in the message (not silently truncates/sanitizes/lowercases). `validate_claim_id` — accepts exactly the generated format (e.g. 32-char lowercase hex); rejects wrong length, uppercase, non-hex characters, path separators, and `..`; raises `ValueError` with the offending value, same as `validate_name`.

### `coordinator.py`
2. `test_coordinator_init.py` — init creates `agents/<id>/inbox/` and `locks/`; rejects an invalid `agent_id` via `validate_name` before touching the filesystem.
3. `test_coordinator_locks.py` — `acquire_lock` returns a `LockHandle` (truthy, carries `lock_name` + an opaque token) on success and `None` on timeout; on successful `mkdir`, an `owner.token` file is written inside the lock dir before the handle is returned; if that token write raises, `acquire_lock` removes the lock dir it just created and treats the attempt as failed (retries within the remaining timeout, or returns `None`) — test via a monkeypatched write that raises on the first attempt only; `release_lock(handle)` reads `owner.token`, and: missing file → no-op; mismatched token (simulate by manually swapping the on-disk token between acquire and release) → no-op, lock dir untouched; matching token → `os.remove(owner.token)` then `os.rmdir(lock_dir)`; a matching token that disappears between the read and the remove (simulated race) is treated as already-released, not an error; an unexpected extra file left in the lock dir alongside a valid matching token causes `rmdir` to fail on a non-empty directory, and this **raises** rather than deleting the extra file or silently leaving an undeletable lock dir; releasing an already-released handle a second time is a no-op; timeout returns `None` with no real sleep; retry-then-succeed via mocked `FileExistsError` once; two-coordinator contention; thread-pool exactly-one-winner race (exactly one thread gets a non-`None` handle); `lock_name` validated via `validate_name` before any `mkdir` attempt.
4. `test_coordinator_atomic_write.py` — writes target content; creates missing parent dirs; rejects a `target_file_path` that resolves outside `mesh_root` (absolute path elsewhere, `..` traversal) with `ValueError`, before any file is touched; rejects a path with any symlink component between `mesh_root` and the target — including a symlink that would still resolve back inside `mesh_root`; temp file uses a collision-resistant name (`tempfile.mkstemp`, not PID-based) so two concurrent writers to the same target never share a temp path; full write sequence is `mkstemp` → write → `flush()` → `os.fsync(fd)` → `close()` → `os.replace()` → best-effort parent-directory fsync that swallows `OSError` (test spies on both fsync calls, and separately confirms a parent-dir-fsync `OSError` doesn't propagate or affect the completed write); descriptor is closed even when a later step fails; cleans up temp file and raises `IOError` on `os.replace` failure; leaves existing target untouched if the temp-file write itself fails; passing a non-JSON-serializable payload (e.g. a `set()`) raises, leaves no temp file, and leaves any existing target untouched.
5. `test_coordinator_state.py` — payload shape (`agent_id`, `timestamp`, `status`, `active_tasks`, `metadata`); `None` metadata defaults to `{}`; provided metadata passed through; delegates to `atomic_write_json` (isolated via spy); a non-serializable value in `extra_metadata` propagates the same clean failure as `atomic_write_json`'s own test (no target/temp file left).
6. `test_coordinator_send_message.py` — raises `FileNotFoundError` for missing target inbox; raises `NotADirectoryError` when `agents/<target_id>/inbox` exists but is a file, not a directory; a symlink at that path is treated as unsupported and fails closed (raises, not resolved/followed); `target_agent_id` validated via `validate_name`; stored envelope shape is `{schema_version, id, created_at, sender, target_agent_id, type, body}`; unique `id`/filename even when the clock returns identical timestamps twice (drives a monotonic counter or `uuid4` suffix); non-serializable `payload` fails cleanly (no message file left in the target inbox); a non-`dict` `body` (e.g. a bare string or list) raises `ValueError` before writing; `message_type` validated (non-empty, ≤64 chars, `[a-z0-9._-]+` pattern) before writing, rejecting empty string, uppercase, and a separator/space-containing value; a `body` whose serialized envelope exceeds the documented size limit (256 KiB, measured as `len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))`) raises `ValueError` before writing, with a boundary test at exactly the limit, one byte over it, and a non-ASCII payload confirming UTF-8 byte length (not character count) is what's enforced.

### `inbox.py`
7. `test_inbox_scan.py` — split into claim and acknowledge, tested separately, plus a thin composition test:
   - **`claim_inbox_messages`**: empty inbox; claims a message via `mkdir(.processing/<claim_id>/)` (not the exclusivity point; on `FileExistsError` from a claim-ID collision, retries with a new ID up to a bounded count — test this by forcing `FileExistsError` on the first generated ID) then `os.rename` of the original message into that dir as `<claim_id>/<original_filename>` (**this rename is the exclusivity point** — two concurrent claims racing the same source message: exactly one rename succeeds, the other gets `FileNotFoundError` and moves on, its now-empty claim dir removed), then writes `<claim_id>/<original_filename>.claim.json` (`claimant_agent_id`, `claimed_at`, a `claim_token` generated via `secrets.token_hex(16)`) via `atomic_write_json` (not a bespoke write — spy-assert it's the same call path coordinator writes use); **returns the claimed messages, their claim IDs, and their tokens without deleting anything**; `max_messages` rejects `0`, negative, non-integer, and over-`MAX_CLAIM_BATCH_SIZE` (50) values with `ValueError` before touching the inbox; with a valid `max_messages`, an inbox larger than the limit leaves exactly `max_messages` claimed and the rest untouched; if the sidecar write raises for one message *after* its rename (monkeypatched failure), that message is excluded from the returned batch, reported distinctly in the result, left in place as a message-without-sidecar orphan (not rolled back), **counts toward `max_messages` for that call** (test: force sidecar-write failure on every attempt and confirm the call claims/orphans exactly `max_messages` source messages total, not more, while returning zero successes), and claiming continues for the remaining eligible messages in the same call; sorted-by-filename processing order (not mtime) — asserted only as "best-effort filename order, no cross-machine causal guarantee"; ignores stray `.tmp_*`/hidden files and anything already in `.processing/`, and reports each ignored filename in `InboxScanResult.ignored` rather than dropping it silently; malformed JSON is quarantined — renamed into `inbox/.invalid/` rather than left in place, reported in `InboxScanResult.skipped`; tolerates `Path.unlink`/rename raising `FileNotFoundError` from a concurrent claim.
   - **`acknowledge_claims(agent_id, claims)`** where `claims` is a list of `{claim_id, claim_token}`: each claim item must be a mapping; each `claim_id` is validated via `validate_claim_id` before touching any path; each `claim_token` must be a non-empty string or the call raises `ValueError` before reading/deleting anything (missing, empty, and non-string token are each tested); deletes the message + sidecar + claim dir only when the given token matches the one in `.claim.json`; per-item result is one of: `acknowledged`; `partial` (the message/sidecar were removed but final claim-dir cleanup failed, e.g. due to an unexpected extra file, and the batch continues); `not-found` (claim ID doesn't exist at all); `token-mismatch` (a *complete* claim exists but the token doesn't match — claim left untouched); or `unacknowledgeable` (the claim dir exists but is one of the three orphan shapes with no valid token to compare against — empty dir, no-sidecar, or malformed-sidecar — reported with which shape, claim left completely untouched); acknowledging a subset of a batch leaves the rest claimed and untouched (repeatable partial ack); calling it twice on the same claim ID+token is safe (second call reports not-found, doesn't raise); a token-mismatch case is tested explicitly against a complete claim (manually swap the on-disk token, same pattern as the lock-token mismatch test); each of the three orphan shapes is tested explicitly against `acknowledge_claims` (not just against `recover_processing`) to confirm it's reported as `unacknowledgeable`, not misreported as `not-found` or `token-mismatch`, and that nothing is deleted.
   - **`scan_and_clear_inbox`**: thin composition test only — asserts it calls `claim_inbox_messages` then `acknowledge_claims` with exactly the claim IDs and tokens it got back (spy-isolated), not a re-test of either's internals.
8. `test_inbox_recovery.py` — `recover_processing(mesh_root, agent_id, older_than_seconds=None, claim_ids=None, action=None)` validates every entry in a caller-supplied `claim_ids` via `validate_claim_id` before touching the filesystem, raising `ValueError` on the first invalid one and touching nothing; is a no-op when called with no stale/matching claims; four orphan shapes handled explicitly, **all age-checked via the same selection rules** (no shape is ever unconditionally acted on): (a) an empty `.processing/<claim_id>/` (crash right after `mkdir`, before rename, **or** a live scanner's normal transient state between its own `mkdir` and rename) is age-checked via the claim directory's own mtime — critically, this means a fresh empty claim dir from an active scanner is left alone by default, only an old one is eligible; when selected and actioned, recovery removes the empty directory because there is no message to move; (b) a claim dir with the message file but no `.claim.json` sidecar is age-checked via the message file's mtime; (c) a claim dir whose sidecar exists but fails to parse (invalid JSON, missing `claimed_at`, or an invalid claimant) is treated like (b) — age-checked via message mtime, with the parse failure reported clearly in the result, not raised; (d) a normal claim (message + valid sidecar) is age-checked via the sidecar's `claimed_at`. Age-based selection (`older_than_seconds`) is documented and tested as a heuristic only; passing explicit `claim_ids` instead recovers exactly those claims regardless of age. `action=None` is dry-run/report-only; `action="requeue"` moves the message back to the inbox root **and raises if a file already exists at that destination** rather than overwriting it; `action="quarantine"` moves it to `.invalid/` with the same fail-closed-on-collision rule; **after a successful move, the sidecar (if present) and the now-empty claim dir are also removed** — tested for a complete claim (sidecar present, contains a `claim_token`) and for the no-sidecar orphan shape (nothing to remove but the dir); if that cleanup step raises after the message was already moved (monkeypatched failure), the result reports a partial recovery rather than raising past a message that's already safely relocated, and no unexpected extra file in the claim dir is ever force-deleted; a claim not selected (too young, or not in `claim_ids`) is left untouched under any action; never called by `scan_and_clear_inbox` itself — this is exclusively an explicit, operator-invoked utility, and the docs should say plainly that it's meant to be run while the target agent's own process is stopped, precisely because empty claim dirs are otherwise ambiguous with a live scanner's in-flight state.
8b. `test_inbox_recover_cli.py` — `recover_main(argv)` maps `--mesh-root`, `--agent-id`, `--older-than-seconds`, repeated `--claim-id` (collected into a list), `--action` (`report`/`requeue`/`quarantine`, mapped to `None`/`"requeue"`/`"quarantine"`), and `--dry-run` onto a call into `recover_processing` (spy-isolated — this is an argument-mapping test, not a re-test of recovery logic); `--dry-run` forces `action=None` even if `--action` was also given; missing required `--mesh-root`/`--agent-id` exits non-zero with a clear usage error rather than raising a raw traceback.

### `rules_template.py`
9. `test_rules_template.py` — default output has required top-level keys (`schema_version`, `network_context`, `model_overrides`, `file_tree_exclusions`); standard exclusion patterns present (`.git`, `__pycache__`, `.venv`, `node_modules`); deep-merge of overrides preserves defaults; override values take precedence; `write_local_rules_template` refuses to overwrite without `force=True`, overwrites when `force=True`; delegates to `atomic_write_json` (spy-isolated). `read_local_rules(mesh_root)` reads back exactly what was written (round-trip test); raises `FileNotFoundError` with a clear message when `config/local_rules.json` doesn't exist yet (mesh not bootstrapped); raises (does not silently return `{}` or partial data) on malformed JSON in the file.

### `bootstrap.py`
10. `test_bootstrap.py` — `bootstrap_mesh(mesh_root, agent_ids, rules_overrides=None, force_rules=False)` creates a coordinator (and thus `agents/<id>/inbox/`, `locks/`) for every id in `agent_ids`, validating each via `validate_name`; rejects `agent_ids` that collide after lowercase normalization (e.g. `agent_mbp` + `Agent_MBP`) before creating anything; writes `config/local_rules.json` via `rules_template` exactly once; raises (does not swallow) `FileExistsError` from the rules-template step when `local_rules.json` already exists and `force_rules=False`; passing `force_rules=True` overwrites it; call order is coordinator/dir creation before the rules-template write.

### Integration (smoke-level, not micro-cycled)
11. `test_bootstrap_integration.py` — one end-to-end run of `bootstrap_mesh` against `tmp_path` asserting the full real directory tree + a valid `local_rules.json`, for the three default agent ids (`agent_mac_mini`, `agent_mbp`, `agent_ollama_local`). No code-deployment shim exists or is tested — the live share is data-only.

### `mcp_server.py` (built)
12. `test_mcp_server.py` — `build_server(mesh_root) -> FastMCP` registers
    exactly `EXPOSED_TOOL_NAMES` (`acquire_lock`, `release_lock`,
    `update_state`, `send_message`, `claim_inbox_messages`,
    `acknowledge_claims`, `read_local_rules`, `health_check`) and nothing
    else — a dedicated test asserts `recover_processing`, `bootstrap_mesh`,
    and `atomic_write_json` are absent from `client.list_tools()`. Each
    tool is exercised end-to-end against a real `tmp_path` mesh root via
    FastMCP's in-memory `Client` (the same "real filesystem, light
    mocking" convention the rest of this suite uses, not heavy spy
    isolation) — one happy-path test per tool plus one error-mapping test
    proving a raised `ValueError`/`FileNotFoundError`/etc. surfaces to the
    client as a `fastmcp.exceptions.ToolError` carrying the real message
    (via `_map_tool_errors`, not FastMCP's default masked-message
    fallback). `CoordinatorRegistry` caches one `AgentMeshCoordinator` per
    `agent_id` string, constructed lazily on first use and reused for
    every later call with that same `agent_id` — a lock round-trip test
    (`acquire_lock` → blocked second acquire → `release_lock` →
    reacquire) and a claim/acknowledge round-trip test both cross multiple
    tool calls to prove the registry's reuse is real, not per-call
    reconstruction. `health_check` is built on the identity-free
    `MeshJsonWriter` rather than going through the registry, specifically
    so calling it never creates a synthetic agent directory as a side
    effect (see the "Repo layout" note on why `health_check` moved to
    `MeshJsonWriter`). The Ollama HTTP wrapper (`TASK-9`) is separate,
    follow-up scope, sharing this module's tool functions and
    `_map_tool_errors` rather than duplicating them.

## Tooling setup

1. Author `pyproject.toml` by hand (repo already has content, don't `uv init` over it): `hatchling` build backend, `requires-python = ">=3.11"`, src-layout pointing at `src/agent_mesh_core`.
2. Dev deps via `uv add --dev pytest ruff` once the file exists.
3. `[project.scripts]` entries: `agent-mesh-bootstrap = "agent_mesh_core.bootstrap:main"` (what `deploy.sh` invokes), `agent-mesh-recover-processing = "agent_mesh_core.inbox:recover_main"` (admin-only, run by hand or from `launchd`/cron for the periodic-requeue recommendation), and `agent-mesh-mcp-server = "agent_mesh_core.mcp_server:main"` (`--mesh-root` required, `--host`/`--port` default to `127.0.0.1`/`8000` — pass the Mac mini's Tailscale IP explicitly at deploy time, per "Operational readiness" below).
4. `[tool.pytest.ini_options] testpaths = ["tests"]`; `[tool.ruff]` with `select = ["E", "F", "I"]`.
5. `.gitignore` (already applied — see repo's `.gitignore`): runtime paths (`.tmp_*`, `*.lock`, `agents/`, `locks/`, `config/*.json` except `*.template.json`), plus standard Python/OS ignores — never track the live execution directory.
6. `uv sync`, then `uv run pytest` / `uv run ruff check .` as the ongoing dev loop.
7. `deploy.sh` — a thin, single-purpose, *local* wrapper (not a TDD cycle): run on the Mac mini, which already has this repo cloned/updated and `uv sync`'d, with `/Users/Shared/AgentMesh` as a local path (no mount involved). **Mesh root and agent IDs are overridable via environment variables, not hard-coded**, so the same script can be smoke-tested against a scratch directory (see Verification below) without touching the real live share:
   ```bash
   MESH_ROOT="${MESH_ROOT:-/Users/Shared/AgentMesh}"
   AGENT_IDS="${AGENT_IDS:-agent_mac_mini,agent_mbp,agent_ollama_local}"
   uv run agent-mesh-bootstrap --mesh-root "$MESH_ROOT" --agent-ids "$AGENT_IDS"
   ```
   All the logic `deploy.sh` depends on (directory creation, refuse-to-overwrite config, duplicate-ID rejection) is already covered by `test_bootstrap.py` and lower-level unit tests.

## Verification

- `uv run pytest -v` — full suite green, including the thread-pool lock race (run a few times to confirm it's not flaky).
- `uv run ruff check .` — clean.
- Manual smoke: instantiate `AgentMeshCoordinator` twice against the same `tmp_path`-like real directory outside pytest (e.g. a scratch dir), exercise `send_message` + inbox scan across the pair, confirm no leftover `.tmp_*` files.
- Manual smoke: run `MESH_ROOT=<scratch dir> deploy.sh` (not the real `/Users/Shared/AgentMesh`) to confirm it produces the same tree `test_bootstrap_integration.py` asserts, then re-run it to confirm `local_rules.json` is left untouched (no `force_rules`).
- Manual smoke: simulate each of the four crash points by hand (empty `.processing/<claim_id>/`; message present with no sidecar; message present with a malformed sidecar; complete claim), confirm `claim_inbox_messages`/`scan_and_clear_inbox` leaves all four alone, then confirm `recover_processing` handles each correctly (dry-run report, then `requeue`/`quarantine`, including the destination-collision-raises case) both via age threshold and via explicit `claim_ids`. Confirm a *fresh* empty claim dir (simulating a live scanner mid-claim) is left alone by a default-threshold `recover_processing` call.
- Manual smoke: claim messages via `claim_inbox_messages` and deliberately *don't* call `acknowledge_claims` (simulating a dropped MCP connection); confirm the claim is inert but present, then confirm `recover_processing(action="requeue")` puts the message back in the inbox once past the age threshold.
- Manual smoke: force a lock-token-write failure and confirm `acquire_lock` leaves no orphaned lock dir; manually place an extra file in an otherwise-releasable lock dir and confirm `release_lock` raises instead of deleting it.
- Manual smoke: claim a message, manually overwrite its `.claim.json`'s `claim_token`, then call `acknowledge_claims` with the original token; confirm the result reports token-mismatch and the claim survives untouched (not deleted).
- Manual smoke: run `agent-mesh-recover-processing --mesh-root <scratch dir> --agent-id <id> --dry-run` against a manually-created stale claim and confirm it reports without modifying anything; re-run with `--action requeue` (no `--dry-run`) and confirm the message returns to the inbox.
- `test_mcp_server.py` now covers every exposed tool against a real
  `tmp_path` mesh root via FastMCP's in-memory `Client` — happy path,
  error-mapping to `ToolError`, and the exact-tool-set assertion.
- Not yet covered here (deferred to `TASK-9`/`TASK-11` in `docs/ROADMAP.md`):
  the Ollama HTTP wrapper, `launchd` restart behavior, and live tool
  registration reachable from a real Claude Code/Codex client over
  Tailscale (in-memory `Client` tests prove the tool layer is wired
  correctly, not that a real network deployment on the Mac mini works).
