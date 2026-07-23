# Role & Goal

> **Superseded — historical draft, do not implement literally.** Steps 3–4 below ask for code and config to be written directly into the live share; see the "Amendment" at the bottom, `../IMPLEMENTATION_PLAN.md`, and `../../AGENTS.md` for the actual v1 design (no code is ever placed in `/Users/Shared/AgentMesh`; it's data-only). **Doubly superseded as of the MCP-server pivot decision (2026-07-23):** the SMB-mount transport assumed throughout (clients mounting `/Users/Shared/AgentMesh` over SMB) is dropped — only the Mac mini ever touches the mesh root, reached by every other machine through an MCP server (Ollama tooling via an HTTP wrapper). See `../PROBLEM_STATEMENT.md`.

You are an expert systems automation engineer setting up a multi-agent file-mesh infrastructure on this host Mac mini. The objective is to establish an always-on, zero-port-forwarding, Tailscale SMB-accessible data directory structured for agent communication (Claude Code, Codex, Ollama cluster) via text, settings, and JSON file primitives.

# System Context
- Host: Always-on Mac mini (macOS) accessible externally via Tailscale.
- Network Target: Clients (MBP M3 Pro, plus upcoming Linux and Windows rigs) will mount this share via its Tailscale IP.
- Expected Messaging Style: Isolated inbox directories, JSON structures, rules sharing, and distributed file trees.

# Tasks to Execute
Please execute the following steps sequentially directly on this system:

1. **Verify or Propose Folder Location**:
   - Check if `/Users/Shared/AgentMesh` exists. If not, create it.
   
2. **Generate the Mesh Directory Architecture**:
   - Programmatically build out the following empty folder hierarchy inside the root folder:
     - `config/`
     - `locks/`
     - `agents/agent_mac_mini/inbox/`
     - `agents/agent_mbp/inbox/`
     - `agents/agent_ollama_local/inbox/`

3. **(historical, superseded — do not run) Deploy Core Coordination Scripts**:
   - ~~Create a Python file named `/Users/Shared/AgentMesh/agent_core.py`~~ — do not do this; see the Amendment below. Original intent, for reference: an `AgentMeshCoordinator` class that handles:
     - Atomic directory-based locks (`os.mkdir` / `os.rmdir`) to prevent race conditions over cross-platform SMB mounts.
     - Atomic JSON operations using local hidden temporary files shifted seamlessly via `shutil.move` to prevent packet-drop JSON corruptions over Tailscale links.
     - An inbox scanning function that processes messages and deletes them out of the agent's inbox folder upon reading.

4. **(historical, superseded — do not run as written) Populate Initial Base Rules**:
   - ~~Create a base configuration file at `config/local_rules.json`~~ directly — this is done via `bootstrap_mesh`/`agent-mesh-bootstrap`, not by an agent writing the file by hand. Original intent, for reference: base configuration metadata detailing global network context, active model overrides for Claude/Ollama, and exclusion guidelines for file tree indexes.

5. **Provide the System Automation Strategy**:
   - Write a short utility script or outline the specific macOS native CLI commands (`sharing` utility, `dscl` commands, or UI guidance) to cleanly export this directory via SMB, ensuring proper Read/Write access flags are pinned for Tailscale connected nodes.

Verify your creations by checking directory structures and mocking an atomic write test script to ensure operations run without warnings.

## Amendment (per PROJECT-SETUP.md and two rounds of adversarial review — see PLAN_FEEDBACK.md, PLAN_FEEDBACK-2.md)

Steps 3 and 4 above, read literally, have an agent write `agent_core.py` and `config/local_rules.json` directly into the live `/Users/Shared/AgentMesh` share. That's superseded, with a firm final call: **no executable code is ever placed in `/Users/Shared/AgentMesh` — it is data-only, permanently.** Source code and templates are developed and version-controlled in this git repo (see `IMPLEMENTATION_PLAN.md` for the `src/agent_mesh_core/` package layout). Each participating machine gets the code via its own independent `git clone`/`git pull` + `uv sync` — that is a per-machine, per-operator action, not something any script pushes out. `deploy.sh` has exactly one job: run locally on a machine that already has the package installed and the share mounted, and populate the live share's *data* (`agents/*/`, `locks/`, `config/local_rules.json`) by invoking the `agent-mesh-bootstrap` console script. It never copies code anywhere. The live share itself is never a git-tracked directory — see `.gitignore` and `AGENTS.md`'s "Repo vs. live share split" section for why. Step 4's "don't overwrite existing config" caveat is implemented once, in Python (`rules_template.write_local_rules_template`'s `force` flag), and reused by `bootstrap_mesh` — not reimplemented as a bash existence check. Note also that `bootstrap_mesh`/`agent-mesh-bootstrap` is operator/admin tooling invoked deliberately against a specific mesh root — it is not part of the runtime API any agent process calls during normal operation.

