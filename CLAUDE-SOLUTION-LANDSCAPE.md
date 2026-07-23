# Solution landscape (independent research)

This is my own "are we reinventing a wheel?" pass, done before reading `SOLUTION_LANDSCAPE.md` (the adversarial reviewer's version), so the comparison in `SOLUTION_RECOMMENDATION.md` is honest rather than anchored on their framing. Sources are linked inline; this reflects research done 2026-07-23.

## Reframing the question

Four rounds of adversarial review (`PLAN_FEEDBACK.md` through `PLAN_FEEDBACK-4.md`) spent a lot of effort hardening a hand-rolled filesystem coordination layer: path validation, lock ownership tokens, atomic-write durability, multi-shape crash recovery for claimed messages. That effort is a signal worth taking seriously — when a design needs four rounds of "but what if it crashes *here*" to reach something defensible, it's worth asking whether the *category* of solution is the expensive part, not the specific bugs.

I looked in three places: (1) generic multi-agent orchestration frameworks, (2) generic messaging/queueing infrastructure, (3) tools built specifically for the actual niche here — coordinating coding-assistant CLIs (Claude Code, Codex, Ollama-backed tools) across machines. (3) turned out to matter most and isn't covered by (1) or (2).

## Category 1: generic agent orchestration frameworks — wrong layer

LangGraph, CrewAI, Microsoft Agent Framework (AutoGen's successor), Google ADK/A2A, and enterprise platforms (Copilot Studio, LangSmith, CrewAI AMP) all solve "build an agentic *application*": graphs/workflows, memory, tool use, retries, human review, hosted deployment. None of them solve "let independently-running CLI tools on different machines pass messages and coordinate over a filesystem they already share." Building or adopting one of these to solve this problem would mean adopting an entire agent-authoring framework just to get a mailbox. Confirmed low overlap; not worth more research time here.

## Category 2: generic messaging/coordination infrastructure — the reviewer's core suggestion, still valid but not free

- **NATS JetStream** — single ~18MB binary, no external deps, gives durable streams, ack/replay, work queues, and KV/object storage out of the box. This is real prior art for exactly the hard parts this project has been hand-rolling (locks, claiming, crash recovery, ordering). It requires running `nats-server` somewhere reachable (the Mac mini, over Tailscale) and switching agents from "write JSON to a mounted folder" to "use a NATS client library." ([nats.io](https://nats.io/), [JetStream docs](https://docs.nats.io/nats-concepts/jetstream))
- **Redis Streams** — consumer groups, a Pending Entries List, `XCLAIM`/`XAUTOCLAIM` for exactly the "claimed but the consumer died" problem this project's `recover_processing` reinvents by hand. Redis 8.4 even added `XREADGROUP ... CLAIM` to combine reclaim-idle-then-read-new in one atomic command — i.e., the upstream project has already iterated past the crash-recovery edge cases this plan is still discovering. Requires a Redis instance. ([Redis streams crash recovery](https://oneuptime.com/blog/post/2026-03-31-redis-handle-consumer-failures-streams/view), [XREADGROUP CLAIM](https://redis.io/blog/single-shot-reliable-consumers-with-xreadgroup-claim-in-redis-84/))
- **Temporal** — durable execution for long-running workflows with retries/compensation. Overkill unless the actual unit of coordination becomes a multi-step workflow that must survive crashes across days, not just message passing. ([temporal.io](https://temporal.io/))

Verdict: if a small always-on service is acceptable, NATS JetStream in particular would eliminate almost every hard problem the last four review rounds fought through, at the cost of adding one dependency (a service to run) and changing the client-side integration from "write files" to "use a client library."

## Category 3: tools built for *this exact niche* — the important finding the reviewer's doc missed

Generic frameworks and generic brokers are the wrong comparison set for the real question, which is narrower: **"multiple coding-assistant CLIs (Claude Code, Codex, Gemini CLI, etc.), on possibly-different machines, need to pass messages/claim work/avoid collisions."** That specific niche already has active open-source projects in 2026:

- **[Shire](https://www.agents-shire.sh/)** (MIT, `npm install -g agents-shire`) — "persistent workspaces for AI agent teams" with an explicit **file-based inter-agent mailbox** and a **shared drive**, no orchestrator required: "Agent A writes a message to Agent B's inbox, and Agent B picks it up on its own schedule." This is describing this project's own design almost word for word. Supports Claude Code, OpenCode, Pi Agent. Its multi-*machine* story isn't clearly documented (it reads as single-host/local-first), so it may not directly solve the "Mac mini + MBP + future Linux/Windows box" requirement, but it's strong evidence the mailbox pattern itself is a solved, packaged idea, not something that needs inventing from a Q&A session.
- **[swarm-protocol](https://github.com/phuryn/swarm-protocol)** (MIT, ~49 stars, alpha, active) — "a headless coordination layer exposed as an MCP server: claim work, detect file conflicts, heartbeat, and hand off tasks across agent sessions." This is architecturally the closest match to the *lock + state + recovery* half of this project, and it's exposed as an **MCP server** — the same protocol Claude Code and Codex already speak natively, meaning zero custom client-side plumbing is needed (no Python package to import into each agent's own loop; just an MCP server registration). It requires a PostgreSQL instance, which reintroduces a service dependency, but a self-hosted Postgres (or a fork using SQLite) on the always-on Mac mini is a small ask.
- **[gnap](https://github.com/farol-team/gnap)** — "Git-Native Agent Protocol": a shared git repo as a `todo/`→`doing/`→`done/` task board, "zero servers." Git already handles the cross-machine sync problem (push/pull) that this project was solving with SMB+Tailscale, and git history gives a free audit trail. Weaker fit for *real-time* locking/messaging (it's asynchronous, commit-cycle-latency, and conflict resolution is git's own merge machinery, not a mutex) — better suited to coarse task handoff than to the sub-second inbox/lock semantics this design targets.
- **[guild](https://github.com/mathomhaus/guild)** — single Go binary + embedded SQLite + MCP server, shared context/memory/task coordination, "atomic locks to claim tasks." Explicitly single-machine/local-only ("state lives strictly on local host; nothing leaves your machine"), so it doesn't solve the cross-machine requirement, but it's more validation that "small local binary + MCP server + SQLite" is a live, current pattern for this problem class, and that others building this have landed on MCP as the interface rather than a shared filesystem.
- **[hcom](https://github.com/aannoo/hcom)** — hooks Claude Code, Codex, Gemini CLI, OpenCode, Cursor CLI, etc. together so they can message/watch/spawn each other across terminals, with a multi-device mode over an **end-to-end-encrypted MQTT relay**. This is a second independent vote for "use a message-relay/broker for the cross-machine hop," not a filesystem mount.
- Also surfaced, less central but worth naming: **buzz** (Nostr-relay-based agent collaboration), **centaur** (Slack-native, Kubernetes-sandboxed team agent platform), **agentsmesh** ("AI Agent Workforce Platform" with cross-channel/pod coordination) — all enterprise-leaning and heavier than this project needs, but all further confirm the pattern of "don't hand-roll the transport; sit a thin coordination layer on top of an existing one."

## A technical risk finding, independent of build-vs-buy

While researching Maildir (the classic prior art for "atomic delivery via write-to-temp-then-move," which is exactly this project's `atomic_write_json` pattern), I found an important caveat: **`rename()` is not reliably atomic over NFS**, which is *why* real Maildir implementations use `link()` + `unlink()` instead of a bare `rename()` on networked mounts. ([Maildir docs](https://cr.yp.to/proto/maildir.html), [Dovecot](https://doc.dovecot.org/2.3/admin_manual/mailbox_formats/maildir/))

This project's entire atomic-write design (`mkstemp` → `os.replace`) assumes `os.replace`/rename *is* atomic over SMB specifically. I could not find an authoritative, unambiguous confirmation that SMB2/3's rename (as exposed through macOS's/Windows'/Samba's SMB client stacks) carries the same atomicity guarantee as a local POSIX rename in every client/server combination this project plans to support (macOS host, macOS/Linux/Windows clients). SMB is a stateful protocol (unlike NFS's classic statelessness) and generally implements rename as a single server-side operation, which is a good sign — but "good sign" is not the same as "verified," and this is exactly the kind of assumption the four adversarial reviews have been chasing edge cases around without ever actually testing against a real SMB mount. **This is a concrete pre-implementation action item regardless of which path is chosen**: write a small script that does concurrent `os.replace` races against the actual Mac mini SMB share from at least two client OSes before trusting either the current design or `IMPLEMENTATION_PLAN.md`'s test suite to have covered the real failure mode.

## Locking libraries: also already solved, with the same caveat

`filelock` (actively maintained, v3.32.0 released 2026-07-21), `fasteners`, and `portalocker` are all mature, cross-platform Python file-locking libraries. Notably, `filelock`'s current release explicitly added **NFS/HPC-cluster reader-writer locks with TTL-based stale detection across hosts** — i.e., a maintained OSS library has already built (and presumably hardened past a similar review gauntlet) almost exactly the "detect and safely break a stale cross-host lock" problem this project's round-1 review pushed us to explicitly *not* build. That's a strong signal this specific sub-problem has a "buy" answer, if the project ends up needing lock semantics beyond the current mkdir/token design. ([filelock docs](https://py-filelock.readthedocs.io/en/latest/))

## The network layer is already solved, and may make SMB unnecessary

Tailscale is already the transport this project assumes for reaching the Mac mini. `tsnet` (Tailscale's embeddable-node library) lets a program join the tailnet directly without a system daemon — but it's Go-first, so it's not a natural fit for this project's Python stack. More importantly, it's not even necessary here: **Tailscale is already running as a system service on every participating machine**, so any of these machines can already reach the Mac mini's Tailscale IP directly over plain TCP/HTTP, with no SMB mount involved at all. That reframes the SMB-mount design as one *specific, and not obviously necessary*, choice for how machines talk to the Mac mini — not the only way. A small HTTP or MCP server bound to the Mac mini's Tailscale interface is an equally "no cloud, no port-forwarding" option, and it sidesteps the SMB rename-atomicity question entirely, since all the actual file writes would then happen on local disk on the Mac mini rather than across a network mount. ([tsnet](https://tailscale.com/kb/1244/tsnet), [Cleric's tsnet writeup](https://tailscale.com/blog/cleric-tsnet-automate-software-operations))

## What's still genuinely specific to this project

- A truly zero-service, "just files on a mount" model, if that constraint is real and non-negotiable (e.g., wanting to eyeball state in Finder without any client library or running process).
- Coordinating *heterogeneous* tools (Claude Code + Codex + Ollama-backed scripts) that don't share a runtime, where even "add an MCP server" is a small but real integration cost per tool.
- A fully version-controlled, revertible logic layer kept separate from live state — a good practice regardless of transport, and not something any of the above tools advertise as a first-class feature.

None of the researched tools are a complete drop-in replacement once cross-machine coordination, zero-cloud, and "works with whatever CLI tool shows up next" are all simultaneously required — but several of them (`swarm-protocol` especially) are close enough that building from scratch should be a deliberate, informed choice, not a default.

## Sources

- [nats.io](https://nats.io/) / [JetStream](https://docs.nats.io/nats-concepts/jetstream)
- [Redis Streams consumer failure handling](https://oneuptime.com/blog/post/2026-03-31-redis-handle-consumer-failures-streams/view) / [XREADGROUP CLAIM (Redis 8.4)](https://redis.io/blog/single-shot-reliable-consumers-with-xreadgroup-claim-in-redis-84/)
- [Temporal](https://temporal.io/)
- [Shire](https://www.agents-shire.sh/)
- [swarm-protocol](https://github.com/phuryn/swarm-protocol)
- [gnap](https://github.com/farol-team/gnap)
- [guild](https://github.com/mathomhaus/guild)
- [hcom](https://github.com/aannoo/hcom)
- [awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators)
- [Maildir spec](https://cr.yp.to/proto/maildir.html), [Dovecot Maildir docs](https://doc.dovecot.org/2.3/admin_manual/mailbox_formats/maildir/)
- [filelock](https://py-filelock.readthedocs.io/en/latest/), [fasteners](https://pypi.org/project/fasteners), [portalocker](https://github.com/wolph/portalocker)
- [tsnet](https://tailscale.com/kb/1244/tsnet), [Cleric tsnet case study](https://tailscale.com/blog/cleric-tsnet-automate-software-operations)
- SQLite-on-network-filesystem hazards: [GoToSocial docs](https://docs.gotosocial.org/en/latest/advanced/sqlite-networked-storage/), [crush issue #473](https://github.com/charmbracelet/crush/issues/473)
