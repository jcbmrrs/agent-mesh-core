# Solution landscape

This note captures a quick "are we reinventing a wheel?" check before implementing the project described in `PROMPT.md`, `PROJECT-SETUP.md`, and `IMPLEMENTATION_PLAN.md`.

## Short answer

Yes, parts of this project overlap with existing open source and commercial software. The important distinction is that existing tools mostly solve one of two broader problems:

- Agent orchestration: agent roles, workflows, memory, tool use, retries, human review, tracing, deployment.
- Messaging and durable coordination: queues, streams, acknowledgements, leases, replay, state, observability.

The proposed Agent Mesh design is narrower: a local/private, filesystem-backed coordination layer for a small set of personal agents on machines connected through a shared SMB mount over Tailscale.

Do not build this as a general multi-agent orchestration framework. That wheel exists. If this project proceeds, keep it deliberately small: a Maildir-like transport and coordination substrate, not an agent platform.

## Existing agent orchestration options

### LangGraph / LangSmith

LangGraph is the strongest existing fit if the goal is durable, stateful agent workflows with precise control. It provides graph-based orchestration, persistence, checkpointing, durable execution, streaming, human-in-the-loop interrupts, memory, and production deployment paths through LangSmith.

Relevant when:

- Workflows have explicit states, branching, retries, review gates, and resumability needs.
- The system should evolve into a production-grade agent runtime.
- Observability, replay, and hosted deployment matter.

Less aligned with this repo's current premise when:

- The primary requirement is cross-machine coordination through an already-mounted local filesystem.
- The desired runtime is intentionally tiny and inspectable, with no database or hosted service.

References:

- https://langchain-ai.github.io/langgraph/reference/
- https://langchain-ai.github.io/langgraph/concepts/langgraph_server/
- https://langchain-ai.github.io/langgraph/concepts/time-travel/
- https://docs.langchain.com/oss/python/langgraph/deploy

### CrewAI / CrewAI AMP

CrewAI is a role-and-task oriented multi-agent framework. It is useful when the system naturally maps to crews of agents with responsibilities, goals, tasks, tools, and process definitions. CrewAI AMP adds a commercial deployment and monitoring layer.

Relevant when:

- The goal is to quickly prototype agent teams.
- Role-based task delegation is the primary abstraction.
- Managed deployment, visual building, tracing, and enterprise controls are valuable.

Less aligned when:

- The core problem is a local coordination substrate for unrelated agent tools rather than one application-level team of agents.
- The project needs filesystem-only coordination semantics rather than a framework runtime.

References:

- https://docs.crewai.com/index
- https://docs.crewai.com/core-concepts/Agents
- https://docs.crewai.com/enterprise/introduction
- https://crewai.com/open-source

### Microsoft Agent Framework / AutoGen

AutoGen popularized conversational multi-agent patterns, but Microsoft's AutoGen repository now describes AutoGen as maintenance-mode and points new projects toward Microsoft Agent Framework. Microsoft Agent Framework provides agents, tools, conversations, memory, persistence, workflows, hosting, A2A support, and MCP-oriented integrations.

Relevant when:

- Conversational or event-driven multi-agent applications are the goal.
- Microsoft ecosystem integration matters.
- A supported framework with Python/.NET paths is preferable.

Less aligned when:

- The design goal is tool-agnostic coordination between local agents through a shared data directory.
- The system should avoid a larger framework commitment.

References:

- https://learn.microsoft.com/en-us/agent-framework/
- https://github.com/microsoft/autogen
- https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/agent-and-agent-runtime.html

### Google ADK / A2A / Agent Runtime

Google's ADK and Agent2Agent-oriented tooling are relevant for multi-agent systems with agent discovery, hosted endpoints, managed sessions, observability, authentication, and cloud deployment. The A2A model treats agents as network-addressable services with agent cards, messages, tasks, and artifacts.

Relevant when:

- Agents need to interoperate across frameworks, teams, services, or organizations.
- Cloud-hosted deployment and managed sessions are acceptable.
- Standard protocol-level interoperability matters more than local filesystem simplicity.

Less aligned when:

- Agents are personal/local tools on private machines and should coordinate without cloud runtime dependencies.

References:

- https://codelabs.developers.google.com/adk-a2a-agent-runtime
- https://codelabs.developers.google.com/codelabs/create-multi-agents-adk-a2a

### Microsoft Copilot Studio and enterprise agent platforms

Commercial platforms such as Microsoft Copilot Studio, Google Gemini Enterprise Agent Platform Runtime, CrewAI AMP, LangSmith, and similar enterprise offerings provide orchestration, connectors, access control, observability, deployment, and governance.

Relevant when:

- The target is enterprise workflow automation.
- Admin controls, SSO/RBAC, hosted deployment, auditability, connectors, and support are worth paying for.

Less aligned when:

- This is a personal/private mesh for heterogeneous local coding and model agents.
- The project intentionally wants version-controlled logic plus a local runtime share.

References:

- https://learn.microsoft.com/en-us/microsoft-copilot-studio/fundamentals-what-is-copilot-studio
- https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-add-other-agents

## Existing messaging and coordination options

### NATS JetStream

NATS JetStream is probably the closest practical replacement if running a small daemon on the Mac mini is acceptable. NATS is open source, lightweight, and available as a single binary. JetStream adds persistence, streams, acknowledgements, replay, work queues, key/value storage, object storage, and atomic key/value operations.

It would likely replace the hardest custom parts of this project:

- Directory lock correctness.
- Inbox claiming.
- Crashed claimant recovery.
- Polling behavior.
- Message replay and acknowledgement semantics.
- Some ordering and deduplication concerns.

Relevant when:

- It is acceptable to run `nats-server` on the Mac mini over Tailscale.
- Agents can use client libraries instead of writing JSON files into SMB folders.
- Correct durable messaging matters more than the simplicity of "just a mounted directory."

Less aligned when:

- A broker process is explicitly unwanted.
- Human-readable files on the shared mount are a core requirement.
- The design must work anywhere SMB works, without installing a service.

References:

- https://docs.nats.io/
- https://docs.nats.io/nats-concepts/what-is-nats
- https://docs.nats.io/nats-concepts/jetstream
- https://docs.nats.io/using-nats/developer/develop_jetstream

### Redis Streams

Redis Streams provide append-only streams, consumer groups, acknowledgements, pending entries, claiming, replay, and configurable retention. Redis is a common choice for moderate-scale job queues and event streams.

Relevant when:

- Redis is already part of the environment or acceptable to run.
- Consumer-group semantics are desirable.
- A straightforward queue/stream model is enough.

Less aligned when:

- Adding another server is undesirable.
- The design must remain filesystem-native and inspectable through Finder/Explorer/shell.

References:

- https://redis.io/docs/latest/develop/use-cases/streaming/
- https://redis.io/docs/latest/develop/data-types/streams/

### Temporal

Temporal is a durable execution system rather than a simple message bus. It is useful when the real unit of coordination is a long-running workflow that must survive crashes, retry safely, preserve state, and expose operational visibility.

Relevant when:

- Agent actions become long-running business workflows.
- Retry, cancellation, compensation, scheduling, and crash recovery are central requirements.
- Operational maturity is more important than minimal setup.

Less aligned when:

- The desired v1 is a tiny coordination directory.
- The system only needs low-volume message exchange and state files.

Reference:

- https://temporal.io/

## What appears genuinely specific about this project

The current design still has a legitimate niche if these constraints are real:

- No cloud dependency.
- No always-on broker beyond SMB/Tailscale.
- Coordination between heterogeneous local agents and tools, not one application framework.
- Human-inspectable JSON state and message files.
- Very low message volume.
- Personal/admin-controlled machines rather than a production SaaS fleet.
- Version-controlled code kept separate from runtime state.
- Conservative SMB-safe filesystem semantics: per-agent inboxes, atomic rename writes, directory-based locks, explicit recovery only.

In that niche, Agent Mesh is closer to a small transport library than to LangGraph, CrewAI, AutoGen, or Copilot Studio.

## Decision guidance

Use LangGraph, CrewAI, Microsoft Agent Framework, Google ADK/A2A, or a commercial platform if the main goal is agent behavior and workflow orchestration.

Use NATS JetStream or Redis Streams if the main goal is reliable cross-process messaging and a small daemon is acceptable.

Use Temporal if the main goal is durable long-running workflows with strong operational semantics.

Proceed with this repo only if the filesystem constraint is intentional and valuable. In that case, scope v1 tightly:

- Implement only the filesystem transport, state writing, name validation, lock primitive, bootstrap tooling, and explicit recovery mechanics described in `IMPLEMENTATION_PLAN.md`.
- Avoid building scheduling, routing intelligence, workflow orchestration, agent memory, tracing, or generalized task execution into this package.
- Treat interoperability with higher-level frameworks as a future adapter layer, not part of the core.

## Recommendation

Before implementing the current plan, decide whether "SMB share only, no broker" is a hard requirement.

If it is not a hard requirement, prototype with NATS JetStream first. It removes much of the correctness risk that this repo is otherwise taking on.

If it is a hard requirement, this project is not pointless, but it should stay intentionally small and boring: a robust filesystem mailbox for personal agents, not a competing multi-agent framework.
