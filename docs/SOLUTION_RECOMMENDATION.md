# Solution recommendation

Synthesizes my independent research (`CLAUDE-SOLUTION-LANDSCAPE.md`) against the adversarial reviewer's (`SOLUTION_LANDSCAPE.md`), then gives a concrete path forward.

## Where the two research passes agree

- **Generic agent orchestration frameworks are the wrong category.** LangGraph, CrewAI, Microsoft Agent Framework, Google ADK/A2A, Copilot Studio, etc. solve "build an agentic application," not "let already-running CLI tools on different machines pass messages." Both docs independently rule these out. Don't reconsider this.
- **NATS JetStream is the strongest general-purpose infrastructure replacement** if a small always-on service is acceptable. It would absorb almost every hard problem the four review rounds fought through by hand: durable claiming, ack/replay, crash recovery. Both docs land here independently.
- **If the filesystem-only constraint is real, keep v1 small** — a transport/mailbox substrate, not a competing framework. Both docs agree on this if the "no broker" path is chosen.

## Where the two research passes diverge

**The reviewer's `SOLUTION_LANDSCAPE.md` stayed at two levels of abstraction: generic agent-application frameworks (LangGraph/CrewAI/AutoGen/ADK) and generic messaging infrastructure (NATS/Redis/Temporal).** It didn't search for tools built for the actual, narrower niche this project is in — coordinating multiple *coding-assistant CLIs* (Claude Code, Codex, Ollama-backed tools) across machines. That niche has its own active 2026 open-source ecosystem that neither the original design docs nor the reviewer surfaced:

- **`swarm-protocol`** — an MCP server for exactly this: claim work, detect file conflicts, heartbeat, hand off tasks across agent sessions. This is architecturally closer to what's actually being built here than NATS or Redis are, because it's exposed over **MCP**, the protocol Claude Code and Codex already speak — meaning no bespoke Python package needs to be imported into anything; it's just another MCP server entry.
- **`Shire`** — a shipping, MIT-licensed, npm-installable tool whose entire pitch is a **file-based inter-agent mailbox with no orchestrator**, i.e., a description of this project's own design, already built and packaged.
- **`gnap`, `guild`, `hcom`** — three more independent, current projects in the same space, each having already made (and shipped) a transport choice: git-as-medium, local-SQLite-behind-MCP, and encrypted-MQTT-relay, respectively. Four different teams converged on "don't hand-roll the transport," none of them on "mount an SMB share and write JSON files directly."

**My research also surfaced a technical risk the reviewer's document didn't examine**: the entire atomic-write design here (`mkstemp` + `os.replace`) assumes rename is atomic over SMB. Real Maildir implementations (the closest classical prior art to this project's write pattern) deliberately avoid bare `rename()` on network filesystems because it's *not* reliably atomic over NFS — they use `link()`+`unlink()` instead. I could not confirm SMB2/3 carries the same guarantee across every macOS/Windows/Linux client combination this project targets. This matters regardless of which path is chosen below: **if any filesystem-mount approach proceeds, this needs an empirical test against the real Mac mini SMB share before the current test suite (which only exercises `tmp_path`, never a real SMB mount) can be trusted to mean anything about production behavior.**

**Neither document's OSS options are a clean drop-in.** `swarm-protocol` needs Postgres; `Shire`'s multi-machine story is unclear/likely single-host; `guild` is explicitly single-machine only; `gnap`'s git-cycle latency doesn't fit real-time locking. So "just adopt X" isn't quite available off the shelf either — but the fact that four independent projects chose "small local service exposed over MCP or a relay" and zero chose "shared SMB mount with hand-rolled locks" is a meaningful signal about where the actual complexity/reliability tradeoff lands.

## Recommendation

**Don't build a general agent framework (already agreed) — and don't finish the current SMB-mount design as-is either. Re-target the already-reviewed coordination logic at a small local MCP server on the Mac mini, reached over Tailscale, instead of a mounted filesystem share.**

Concretely:

1. **Keep almost everything already designed and reviewed in `IMPLEMENTATION_PLAN.md`.** The lock-with-ownership-token, atomic-write-with-fsync, claim-directory-with-recovery, and name-validation logic are all still valuable — they just stop needing to defend against *network-filesystem* failure modes, because they'd now run against local disk on the Mac mini rather than a share mounted by other machines. This preserves the sunk cost of four rounds of careful review rather than discarding it.
2. **Replace the transport.** Instead of `/Users/Shared/AgentMesh` mounted via SMB from every machine, run a small MCP server process on the Mac mini (bound to its Tailscale IP, reachable from the MBP and future Linux/Windows boxes with zero port-forwarding — Tailscale already provides this). Claude Code and Codex register it as an MCP server directly; no filesystem mount, no SMB rename-atomicity question, no cross-platform locking uncertainty, because there's only ever one machine touching the disk.
3. **Expose the existing coordinator methods as MCP tools, not as a Python package other agents import.** `acquire_lock`/`release_lock`/`send_message`/`scan_and_clear_inbox`/`update_state` become MCP tool calls (`agent_mesh.acquire_lock`, etc.) instead of methods on an imported class. This matches how `swarm-protocol` and `guild` are already built, and removes the awkward unanswered question in the original design of *what process actually calls `AgentMeshCoordinator`'s methods* — the answer becomes simply "whichever agent's MCP client calls the tool."
4. **Ollama-backed local tooling**, which doesn't natively speak MCP, gets a thin HTTP wrapper around the same server (a few routes calling the same underlying functions) — cheaper than teaching every non-MCP tool to mount SMB and import a Python package correctly.
5. **Do the SMB rename-atomicity test anyway, but only if item 6 below turns out to matter.** If the human operator later decides the mesh *also* needs human-inspectable JSON files sitting on a plain network share (e.g., to peek at state in Finder without a client), that's an optional read-only or best-effort mirror written by the one process that already owns local disk — not a requirement for every machine to write to a shared mount.

## The one open decision only the human operator can make

Is "no running service, ever — just a mounted share" a hard, non-negotiable requirement (e.g., for inspectability, or distrust of running another daemon)? If yes, the MCP-server pivot above doesn't apply, and the right move is to keep the current filesystem design but (a) explicitly budget time for the SMB rename-atomicity validation before trusting any of it in production, and (b) seriously evaluate forking or adopting `swarm-protocol`'s SQLite-backed cousin pattern or `filelock`'s NFS-hardened reader-writer locks rather than continuing to hand-roll and re-review lock/claim edge cases indefinitely.

If a small local service is acceptable (it already is, implicitly — Tailscale itself is a always-on background service on every machine here), the MCP-server pivot is the stronger choice: it keeps the reviewed logic, removes the least-verified assumption in the whole design (SMB rename atomicity), and aligns with the toolchain (Claude Code, Codex) that's already MCP-native rather than requiring every future agent to speak "mount a share and import a Python class."
